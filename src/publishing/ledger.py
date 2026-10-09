"""Rollback-resistant operational publication truth, separate from generated output."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from typing import Any, Iterator

SCHEMA_VERSION=1
LEDGER_STATES={"CONFIRMED_PUBLISHED","PUBLISHING_UNCERTAIN","CONFIRMED_NOT_PUBLISHED","RECONCILIATION_REQUIRED"}

class LedgerError(RuntimeError):pass
class LedgerUnavailable(LedgerError):pass
class LedgerConflict(LedgerError):pass

class PublicationLedger:
    def __init__(self,root:Path)->None:
        self.root=root;self.directory=root/"state"/"publishing";self.path=self.directory/"publication-ledger.sqlite3";self.backup_directory=self.directory/"backups";self.established_marker=self.directory/"ledger-established.json"

    def initialize(self,*,fresh:bool,confirmed_receipts:list[dict[str,Any]]|None=None)->None:
        receipts=confirmed_receipts or []
        if self.path.exists():self._validate();self._mark_established();return
        if not fresh and not receipts:raise LedgerUnavailable("PUBLICATION_LEDGER_UNAVAILABLE: established publishing state requires authoritative migration")
        self.directory.mkdir(parents=True,exist_ok=True)
        try:
            with self._connect(create=True) as db:
                db.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
                db.execute("""CREATE TABLE publications(
                  ledger_record_id TEXT PRIMARY KEY, publication_identity TEXT NOT NULL UNIQUE,
                  semantic_creative_identity TEXT NOT NULL, project_id TEXT NOT NULL, platform TEXT NOT NULL,
                  surface TEXT NOT NULL, format TEXT NOT NULL, package_id TEXT, production_contract_version TEXT,
                  media_hashes_json TEXT NOT NULL, provenance_ids_json TEXT NOT NULL, caption_hash TEXT,
                  payload_hash TEXT, account_id TEXT, remote_media_id TEXT, parent_container_id TEXT,
                  child_container_ids_json TEXT NOT NULL, publication_timestamp TEXT, confirmation_timestamp TEXT,
                  state TEXT NOT NULL, attempt_identity TEXT, receipt_id TEXT, receipt_version TEXT NOT NULL,
                  created_at TEXT NOT NULL, CHECK(state IN ('CONFIRMED_PUBLISHED','PUBLISHING_UNCERTAIN','CONFIRMED_NOT_PUBLISHED','RECONCILIATION_REQUIRED'))
                )""");db.execute("CREATE INDEX publications_project_surface ON publications(project_id,surface,state)");db.execute("INSERT INTO metadata(key,value) VALUES('schema_version',?)",(str(SCHEMA_VERSION),));db.execute("INSERT INTO metadata(key,value) VALUES('created_at',?)",(_now(),));db.execute("INSERT INTO metadata(key,value) VALUES('migration_state',?)",("fresh" if fresh and not receipts else "migrated",))
            if receipts:self.migrate_receipts(receipts)
            self._mark_established()
        except (sqlite3.Error,OSError) as error:
            self.path.unlink(missing_ok=True);raise LedgerUnavailable("Unable to initialize durable publication ledger") from error

    def _mark_established(self)->None:
        if not self.established_marker.is_file():_atomic_json(self.established_marker,{"schema_version":"1.0.0","established":True,"created_at":_now()})

    @contextmanager
    def _connect(self,*,create:bool=False)->Iterator[sqlite3.Connection]:
        if not create and not self.path.is_file():raise LedgerUnavailable("PUBLICATION_LEDGER_UNAVAILABLE")
        try:
            db=sqlite3.connect(self.path,timeout=5,isolation_level=None);db.row_factory=sqlite3.Row;db.execute("PRAGMA foreign_keys=ON");db.execute("PRAGMA busy_timeout=5000");db.execute("PRAGMA journal_mode=WAL");db.execute("PRAGMA synchronous=FULL");db.execute("BEGIN IMMEDIATE")
            yield db;db.execute("COMMIT")
        except sqlite3.DatabaseError as error:
            try:db.execute("ROLLBACK")
            except Exception:pass
            raise LedgerUnavailable("PUBLICATION_LEDGER_CORRUPT_OR_LOCKED") from error
        finally:
            try:db.close()
            except Exception:pass

    def _validate(self)->None:
        with self._connect() as db:
            version=db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
            if not version or int(version[0])!=SCHEMA_VERSION:raise LedgerUnavailable("PUBLICATION_LEDGER_SCHEMA_UNSUPPORTED")
            check=db.execute("PRAGMA quick_check").fetchone()
            if not check or check[0]!="ok":raise LedgerUnavailable("PUBLICATION_LEDGER_CORRUPT")

    def reserve(self,item:dict[str,Any],payload:dict[str,Any],account_id:str,config:dict[str,Any])->dict[str,Any]:
        """Atomically check all durable authority and commit intent before Meta."""
        from .eligibility import select_next_eligible_publication
        if not account_id:raise LedgerConflict("Publish intent requires a validated account")
        self._validate()
        identity=item.get("publication_identity") or item.get("idempotency_key")
        with self._connect() as db:
            rows=[_sequence_decode(row,db) for row in db.execute("SELECT * FROM publications")]
            if any(row["publication_identity"]==identity for row in rows):raise LedgerConflict("Publication identity is already reserved")
            if any(row["state"] in {"PUBLISHING_UNCERTAIN","RECONCILIATION_REQUIRED"} for row in rows):raise LedgerConflict("An unresolved publish intent blocks account publishing")
            receipts=[{**row,"status":"published","published_at":row.get("publication_timestamp")} for row in rows if row["state"]=="CONFIRMED_PUBLISHED"]
            selection=select_next_eligible_publication({"items":[item]},receipts,now=datetime.now(timezone.utc),config=config)
            if selection.get("selected_queue_item_id")!=item.get("queue_item_id"):raise LedgerConflict("Durable reservation is not currently eligible")
            value=uncertain_from_item(item,{})
            value.update(state="RECONCILIATION_REQUIRED",account_id=account_id,payload_hash=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest())
            if item.get("campaign_scope"):
                db.execute("INSERT INTO metadata(key,value) VALUES(?,?)",("campaign:"+str(identity),json.dumps(item["campaign_scope"],sort_keys=True)))
            if item.get("project_sequence"):
                db.execute("INSERT INTO metadata(key,value) VALUES(?,?)",("sequence:"+str(identity),json.dumps(item["project_sequence"],sort_keys=True)))
            record=_normalize(value)
            db.execute("INSERT INTO publications VALUES("+",".join("?" for _ in _COLUMNS)+")",tuple(record[x] for x in _COLUMNS))
        return self.get(identity)

    def checkpoint(self,identity:str,attempt:str,event:str,details:dict[str,Any])->None:
        """Append durable remote-call evidence and retain known IDs atomically."""
        with self._connect() as db:
            row=db.execute("SELECT * FROM publications WHERE publication_identity=?",(identity,)).fetchone()
            if not row:raise LedgerConflict("Remote write has no durable intent")
            current=_decode(row)
            if current["attempt_identity"]!=attempt or current["state"]=="CONFIRMED_PUBLISHED":raise LedgerConflict("Checkpoint attempt mismatch")
            db.execute("CREATE TABLE IF NOT EXISTS remote_checkpoints(sequence INTEGER PRIMARY KEY AUTOINCREMENT,publication_identity TEXT NOT NULL,attempt_identity TEXT NOT NULL,event TEXT NOT NULL,details_json TEXT NOT NULL,created_at TEXT NOT NULL)")
            safe={key:details[key] for key in ("role","remote_id","container_id","success") if key in details}
            db.execute("INSERT INTO remote_checkpoints(publication_identity,attempt_identity,event,details_json,created_at) VALUES(?,?,?,?,?)",(identity,attempt,event,json.dumps(safe),_now()))
            remote_id=details.get("remote_id")
            if event=="after_write" and remote_id:
                role=details.get("role")
                if role=="publish":db.execute("UPDATE publications SET remote_media_id=? WHERE publication_identity=?",(remote_id,identity))
                elif role=="parent":db.execute("UPDATE publications SET parent_container_id=? WHERE publication_identity=?",(remote_id,identity))
                elif role=="child":
                    children=list(dict.fromkeys([*current["child_container_ids"],remote_id]))
                    db.execute("UPDATE publications SET child_container_ids_json=? WHERE publication_identity=?",(json.dumps(children),identity))

    def capture_failure(self,item:dict[str,Any],details:dict[str,Any])->None:
        identity=item.get("publication_identity") or item.get("idempotency_key")
        current=self.get(identity)
        if not current:return
        # Preserve IDs checkpointed before a later exception or lost response.
        value=uncertain_from_item(item,details)
        for key in ("remote_media_id","parent_container_id","child_container_ids"):
            if not value.get(key):value[key]=current.get(key)
        value.update(account_id=current.get("account_id"),payload_hash=current.get("payload_hash"),media_hashes=current.get("media_hashes",[]))
        self.record(value)

    def get(self,publication_identity:str)->dict[str,Any]|None:
        self._validate()
        with self._connect() as db:
            row=db.execute("SELECT * FROM publications WHERE publication_identity=?",(publication_identity,)).fetchone()
            return _sequence_decode(row,db) if row else None

    def records(self,*,project_id:str|None=None)->list[dict[str,Any]]:
        self._validate()
        with self._connect() as db:
            rows=db.execute("SELECT * FROM publications WHERE project_id=? ORDER BY created_at",(project_id,)).fetchall() if project_id else db.execute("SELECT * FROM publications ORDER BY created_at").fetchall()
            return [_sequence_decode(x,db) for x in rows]

    def record(self,value:dict[str,Any])->dict[str,Any]:
        state=str(value.get("state"));identity=str(value.get("publication_identity") or "")
        if state not in LEDGER_STATES or not identity:raise LedgerConflict("Invalid ledger record")
        record=_normalize(value)
        with self._connect() as db:
            existing=db.execute("SELECT * FROM publications WHERE publication_identity=?",(identity,)).fetchone()
            if existing:
                old=_decode(existing)
                if old["state"]=="CONFIRMED_PUBLISHED":
                    if state=="CONFIRMED_PUBLISHED" and old.get("remote_media_id")==record.get("remote_media_id"):return old
                    raise LedgerConflict("Confirmed publication identity is immutable")
                db.execute("DELETE FROM publications WHERE publication_identity=?",(identity,))
            db.execute("INSERT INTO publications VALUES("+",".join("?" for _ in _COLUMNS)+")",tuple(record[x] for x in _COLUMNS))
        return self.get(identity) or record

    def confirmed_identities(self)->set[str]:return {x["publication_identity"] for x in self.records() if x["state"]=="CONFIRMED_PUBLISHED"}

    def migrate_receipts(self,receipts:list[dict[str,Any]])->dict[str,Any]:
        imported=reused=0
        for receipt in receipts:
            if receipt.get("status") not in {"published","published_with_warnings"} or not receipt.get("published_media_id") or not receipt.get("publication_identity"):continue
            existing=self.get(str(receipt["publication_identity"]))
            value=record_from_receipt(receipt)
            if existing:
                if existing.get("remote_media_id")!=value.get("remote_media_id"):raise LedgerConflict("Conflicting authoritative receipt migration")
                reused+=1
            else:self.record(value);imported+=1
        report={"schema_version":SCHEMA_VERSION,"imported":imported,"reused":reused,"status":"completed","created_at":_now()};self.directory.mkdir(parents=True,exist_ok=True);_atomic_json(self.directory/"migration-audit.json",report);return report

    def reconcile_queue(self,queue:dict[str,Any])->dict[str,Any]:
        records={x["publication_identity"]:x for x in self.records()}
        for item in queue.get("items",[]):
            record=records.get(item.get("publication_identity"))
            if not record and item.get("status")=="publishing":
                evidence=uncertain_from_item(item,{});evidence["state"]="RECONCILIATION_REQUIRED";record=self.record(evidence);records[record["publication_identity"]]=record
            if not record:continue
            if record["state"]=="CONFIRMED_PUBLISHED":item["status"]="published";item["ledger_record_id"]=record["ledger_record_id"];item["published_media_id"]=record.get("remote_media_id")
            elif record["state"] in {"PUBLISHING_UNCERTAIN","RECONCILIATION_REQUIRED"}:item["status"]="publishing_uncertain";item["ledger_record_id"]=record["ledger_record_id"]
        return queue

    def backup(self,*,keep:int=3)->Path:
        self._validate();self.backup_directory.mkdir(parents=True,exist_ok=True);destination=self.backup_directory/f"ledger-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.sqlite3"
        try:
            source=sqlite3.connect(self.path);target=sqlite3.connect(destination);source.backup(target);target.close();source.close()
            checker=sqlite3.connect(destination);check=checker.execute("PRAGMA quick_check").fetchone();checker.close()
            if not check or check[0]!="ok":raise LedgerUnavailable("Ledger backup validation failed")
        except sqlite3.Error as error:raise LedgerUnavailable("Ledger backup failed") from error
        backups=sorted(self.backup_directory.glob("ledger-*.sqlite3"),reverse=True)
        for stale in backups[max(1,keep):]:stale.unlink()
        return destination

    def status(self)->dict[str,Any]:
        rows=self.records();confirmed=[x for x in rows if x["state"]=="CONFIRMED_PUBLISHED"]
        return {"schema_version":SCHEMA_VERSION,"database_health":"PASS","path":str(self.path),"confirmed_publications":len(confirmed),"uncertain_publications":sum(x["state"]=="PUBLISHING_UNCERTAIN" for x in rows),"reconciliation_required":sum(x["state"]=="RECONCILIATION_REQUIRED" for x in rows),"last_confirmed_publication":max((x.get("publication_timestamp") or "" for x in confirmed),default=None),"project_counts":_counts(rows,"project_id"),"surface_counts":_counts(rows,"surface"),"backup_count":len(list(self.backup_directory.glob("ledger-*.sqlite3"))) if self.backup_directory.exists() else 0}

    def reconcile_publication(self,publication_identity:str,adapter:Any,*,dry_run:bool=False)->dict[str,Any]:
        record=self.get(publication_identity)
        if not record:return {"result":"IDENTITY_MISMATCH","publication_identity":publication_identity,"mutated":False}
        if record["state"]=="CONFIRMED_PUBLISHED":return {"result":"CONFIRMED_PUBLISHED","publication_identity":publication_identity,"mutated":False,"ledger_record_id":record["ledger_record_id"]}
        account=getattr(adapter,"account",{}) or {};configured_account=account.get("instagram_account_id")
        if record.get("account_id") and not configured_account:return {"result":"IDENTITY_MISMATCH","publication_identity":publication_identity,"mutated":False,"reason":"Account-bound recovery requires a validated adapter account."}
        if record.get("account_id") and configured_account and record["account_id"]!=configured_account:return {"result":"IDENTITY_MISMATCH","publication_identity":publication_identity,"mutated":False,"reason":"Ledger account does not match the configured Instagram account."}
        media_id=record.get("remote_media_id")
        try:
            if media_id:remote=adapter.get_status({"published_media_id":media_id})
            elif record.get("parent_container_id") and record.get("account_id") and configured_account==record["account_id"] and callable(getattr(adapter,"get_container_status",None)):
                remote=adapter.get_container_status(record["parent_container_id"])
            else:return {"result":"STILL_UNCERTAIN","publication_identity":publication_identity,"mutated":False,"reason":"No account-bound authoritative remote evidence is available."}
        except Exception:return {"result":"REMOTE_LOOKUP_UNAVAILABLE","publication_identity":publication_identity,"mutated":False}
        status=remote.get("status") if isinstance(remote,dict) else str(remote)
        if status=="published":
            if not dry_run:self.record({**record,"state":"CONFIRMED_PUBLISHED","confirmation_timestamp":_now(),"publication_timestamp":record.get("publication_timestamp") or remote.get("timestamp") or _now()})
            return {"result":"CONFIRMED_PUBLISHED","publication_identity":publication_identity,"mutated":not dry_run,"dry_run":dry_run,"remote":remote}
        if status=="definitively_not_published":
            if not dry_run:self.record({**record,"state":"CONFIRMED_NOT_PUBLISHED","confirmation_timestamp":_now()})
            return {"result":"CONFIRMED_NOT_PUBLISHED","publication_identity":publication_identity,"mutated":not dry_run,"dry_run":dry_run}
        return {"result":"STILL_UNCERTAIN","publication_identity":publication_identity,"mutated":False,"remote":remote}

def record_from_receipt(receipt:dict[str,Any])->dict[str,Any]:
    return {**receipt,"state":"CONFIRMED_PUBLISHED","remote_media_id":receipt.get("published_media_id"),"publication_timestamp":receipt.get("published_at"),"confirmation_timestamp":receipt.get("published_at"),"account_id":receipt.get("instagram_account_id"),"attempt_identity":receipt.get("attempt_token"),"receipt_version":"1.0.0"}

def uncertain_from_item(item:dict[str,Any],remote:dict[str,Any])->dict[str,Any]:return {**item,"publication_identity":item.get("publication_identity") or item.get("idempotency_key"),"state":"PUBLISHING_UNCERTAIN","remote_media_id":remote.get("published_media_id"),"parent_container_id":remote.get("parent_container_id"),"child_container_ids":remote.get("child_container_ids",[]),"publication_timestamp":None,"confirmation_timestamp":None,"account_id":item.get("account_id"),"attempt_identity":item.get("attempt_token"),"receipt_id":None,"receipt_version":"1.0.0","provenance_ids":[],"media_hashes":item.get("image_hashes",[])}

_COLUMNS=("ledger_record_id","publication_identity","semantic_creative_identity","project_id","platform","surface","format","package_id","production_contract_version","media_hashes_json","provenance_ids_json","caption_hash","payload_hash","account_id","remote_media_id","parent_container_id","child_container_ids_json","publication_timestamp","confirmation_timestamp","state","attempt_identity","receipt_id","receipt_version","created_at")
def _normalize(v):
    identity=str(v["publication_identity"]);created=v.get("created_at") or _now();return {"ledger_record_id":v.get("ledger_record_id") or "ledger_"+hashlib.sha256(identity.encode()).hexdigest()[:24],"publication_identity":identity,"semantic_creative_identity":str(v.get("semantic_creative_identity") or "unknown"),"project_id":str(v.get("project_id") or ""),"platform":str(v.get("platform") or "Instagram"),"surface":str(v.get("surface") or "feed"),"format":str(v.get("format") or "single_image"),"package_id":v.get("package_id"),"production_contract_version":v.get("production_contract_version"),"media_hashes_json":json.dumps(v.get("media_hashes",[])),"provenance_ids_json":json.dumps(v.get("provenance_ids") or v.get("source_asset_order",[])),"caption_hash":v.get("caption_hash"),"payload_hash":v.get("payload_hash"),"account_id":v.get("account_id"),"remote_media_id":v.get("remote_media_id"),"parent_container_id":v.get("parent_container_id"),"child_container_ids_json":json.dumps(v.get("child_container_ids",[])),"publication_timestamp":v.get("publication_timestamp"),"confirmation_timestamp":v.get("confirmation_timestamp"),"state":v["state"],"attempt_identity":v.get("attempt_identity"),"receipt_id":v.get("receipt_id"),"receipt_version":str(v.get("receipt_version") or "1.0.0"),"created_at":created}
def _decode(row):
    value=dict(row);value["media_hashes"]=json.loads(value.pop("media_hashes_json"));value["provenance_ids"]=json.loads(value.pop("provenance_ids_json"));value["child_container_ids"]=json.loads(value.pop("child_container_ids_json"));return value
def _counts(rows,key):return {value:sum(x.get(key)==value for x in rows) for value in sorted({str(x.get(key)) for x in rows})}
def _now():return datetime.now(timezone.utc).isoformat()
def _atomic_json(path,value):path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix(".tmp");temp.write_text(json.dumps(value,indent=2,ensure_ascii=False)+"\n",encoding="utf-8");temp.replace(path)


def _sequence_decode(row,db):
    value=_decode(row)
    entry=db.execute("SELECT value FROM metadata WHERE key=?",("sequence:"+value["publication_identity"],)).fetchone()
    if entry:value["project_sequence"]=json.loads(entry[0])
    campaign=db.execute("SELECT value FROM metadata WHERE key=?",("campaign:"+value["publication_identity"],)).fetchone()
    if campaign:value["campaign_scope"]=json.loads(campaign[0])
    return value
