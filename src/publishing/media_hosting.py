"""Cloudflare R2 media hosting for Meta's public-URL publishing requirement."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

POLICY_VERSION = "r2-object-key-v1"
R2_ENV = ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME", "R2_ENDPOINT_URL", "R2_PUBLIC_BASE_URL")


class MediaHostingError(RuntimeError):
    def __init__(self, message: str, classification: str, *, retryable: bool = False) -> None:
        super().__init__(message); self.classification = classification; self.retryable = retryable


def _now() -> str: return datetime.now(timezone.utc).isoformat()
def _slug(value: Any) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "unknown")).strip("-._").lower()
    return clean or "unknown"
def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()
def deterministic_object_key(project: str, release_id: str, platform: str, package_id: str, branded_item_id: str, sha256: str, extension: str) -> str:
    ext = re.sub(r"[^a-z0-9]", "", extension.casefold().lstrip(".")) or "bin"
    return f"projects/{_slug(project)}/{_slug(release_id)}/{_slug(platform)}/{_slug(package_id)}/{_slug(branded_item_id)}-{sha256[:16]}.{ext}"


class CloudflareR2MediaHost:
    provider = "cloudflare_r2"
    def __init__(self, root: Path, *, env: dict[str, str] | None = None, client: Any = None,
                 verifier: Callable[[str], dict[str, Any]] | None = None, timeout: float = 15) -> None:
        if env is None:
            try:
                from dotenv import load_dotenv
                load_dotenv(root/".env")
            except ImportError: pass
        self.root = root; self.env = env or {name: os.getenv(name, "") for name in R2_ENV}; self.timeout = timeout; self.verifier = verifier
        self.bucket = self.env["R2_BUCKET_NAME"].strip(); self.endpoint = self.env["R2_ENDPOINT_URL"].strip().rstrip("/"); self.public_base = self.env["R2_PUBLIC_BASE_URL"].strip().rstrip("/")
        self._client = client
    @property
    def configured(self) -> bool: return all(self.env.get(name, "").strip() for name in R2_ENV)
    def _s3(self) -> Any:
        if self._client is not None: return self._client
        if not self.configured: raise MediaHostingError("Cloudflare R2 credentials or configuration are missing", "missing_credentials")
        try: import boto3
        except ImportError as error: raise MediaHostingError("The boto3 dependency is required for Cloudflare R2", "configuration_error") from error
        self._client = boto3.client("s3", endpoint_url=self.endpoint, aws_access_key_id=self.env["R2_ACCESS_KEY_ID"], aws_secret_access_key=self.env["R2_SECRET_ACCESS_KEY"], region_name="auto")
        return self._client
    def public_url(self, key: str) -> str:
        parsed = urlparse(self.public_base)
        if parsed.scheme.casefold() != "https" or not parsed.netloc: raise MediaHostingError("R2 public base URL must be HTTPS", "configuration_error")
        return f"{self.public_base}/{quote(key, safe='/._-')}"
    def verify_accessibility(self, url: str) -> dict[str, Any]:
        if self.verifier: return self.verifier(url)
        try:
            with urlopen(Request(url, method="HEAD", headers={"User-Agent":"InstagramAgentMediaHost/1.0"}), timeout=self.timeout) as response:
                return {"accessible": 200 <= response.status < 400, "content_type": response.headers.get("Content-Type", "").split(";",1)[0].strip().casefold()}
        except HTTPError as error: return {"accessible": False, "status": error.code, "content_type": ""}
        except (URLError, TimeoutError, OSError): return {"accessible": False, "content_type": ""}
    def status(self) -> dict[str, Any]:
        bucket_access = False; error = None
        if self.configured:
            try: self._s3().head_bucket(Bucket=self.bucket); bucket_access = True
            except Exception: error = "bucket_access_failed"
        delivery = False
        if self.public_base:
            parsed=urlparse(self.public_base); delivery=parsed.scheme.casefold()=="https" and bool(parsed.netloc)
        return {"provider":self.provider,"configured":self.configured,"bucket":self.bucket or "Not configured","endpoint_configured":bool(self.endpoint),"public_base_url_configured":bool(self.public_base),"credentials_present":bool(self.env.get("R2_ACCESS_KEY_ID") and self.env.get("R2_SECRET_ACCESS_KEY")),"bucket_access":bucket_access,"public_delivery":delivery,"ready":self.configured and bucket_access and delivery,"error":error,"warnings":["Using R2 Public Development URL; use a custom domain for production."] if ".r2.dev" in self.public_base else []}
    def upload(self, local_path: Path, *, project_id: str, release_id: str, platform: str, package_id: str, branded_item_id: str) -> dict[str, Any]:
        if not local_path.is_file(): raise MediaHostingError("Eligible branded image does not exist", "configuration_error")
        sha = file_sha256(local_path); content_type = (mimetypes.guess_type(local_path.name)[0] or "").casefold()
        if not content_type.startswith("image/"): raise MediaHostingError("Eligible media has an invalid image content type", "invalid_content_type")
        key = deterministic_object_key(project_id, release_id, platform, package_id, branded_item_id, sha, local_path.suffix)
        url = self.public_url(key)
        try: self._s3().upload_file(str(local_path), self.bucket, key, ExtraArgs={"ContentType":content_type})
        except MediaHostingError: raise
        except Exception as error: raise MediaHostingError("Cloudflare R2 upload failed", "upload_failed", retryable=True) from error
        check = self.verify_accessibility(url)
        if not check.get("accessible"): raise MediaHostingError("Uploaded R2 public URL is unreachable", "public_url_unreachable", retryable=True)
        if not str(check.get("content_type","")).casefold().startswith("image/"): raise MediaHostingError("R2 public URL did not return image media", "invalid_content_type")
        now=_now(); return {"project_id":project_id,"release_id":release_id,"package_id":package_id,"branded_item_id":branded_item_id,"platform":platform,"local_path":str(local_path.resolve()),"local_sha256":sha,"bucket":self.bucket,"object_key":key,"public_url":url,"content_type":content_type,"uploaded_at":now,"verified_at":now,"verified_accessible":True,"provider":self.provider,"object_key_policy_version":POLICY_VERSION}


def manifest_path(root: Path, project: str) -> Path: return root/"output"/"publishing"/"media-hosting"/f"{project}-r2-media.json"
def run_media_hosting(root: Path, project: str, *, host: CloudflareR2MediaHost | None = None) -> tuple[Path, dict[str, int]]:
    host=host or CloudflareR2MediaHost(root); package_path=root/"output"/"post-packages"/f"{project}-post-packages.json"
    if not package_path.is_file(): raise MediaHostingError("Post-package artifact is missing", "configuration_error")
    packages=json.loads(package_path.read_text(encoding="utf-8")); path=manifest_path(root,project); old=json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"records":[]}
    records=[]; stats={"eligible":0,"uploaded":0,"reused":0,"failed":0,"verified_public_urls":0,"meta_write_requests":0}
    prior={(x.get("local_sha256"),x.get("object_key")):x for x in old.get("records",[])}
    for package in packages.get("packages",[]):
        release_id=str(package.get("release_id") or packages.get("release_id") or "unknown"); platform=str(package.get("platform") or "instagram")
        slides=package.get("slides") or ([package["image"]] if isinstance(package.get("image"),dict) else [])
        for slide in slides:
            local=Path(str(slide.get("image_path", ""))); branded=str(slide.get("branded_item_id") or slide.get("provenance_id") or local.stem); stats["eligible"]+=1
            try:
                sha=file_sha256(local); key=deterministic_object_key(project,release_id,platform,str(package.get("package_id")),branded,sha,local.suffix); existing=prior.get((sha,key))
                if existing:
                    check=host.verify_accessibility(existing["public_url"])
                    if check.get("accessible") and str(check.get("content_type","")).startswith("image/"):
                        existing={**existing,"verified_at":_now(),"verified_accessible":True}; records.append(existing); stats["reused"]+=1;stats["verified_public_urls"]+=1;continue
                record=host.upload(local,project_id=project,release_id=release_id,platform=platform,package_id=str(package.get("package_id")),branded_item_id=branded);records.append(record);stats["uploaded"]+=1;stats["verified_public_urls"]+=1
            except (OSError,MediaHostingError): stats["failed"]+=1
    value={"project_id":project,"provider":"cloudflare_r2","cleanup_policy":"retain","object_key_policy_version":POLICY_VERSION,"records":records,"summary":stats,"updated_at":_now(),"warnings":["Using R2 Public Development URL; use a custom domain for production."] if ".r2.dev" in host.public_base else []}
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(".tmp");tmp.write_text(json.dumps(value,indent=2,ensure_ascii=False)+"\n",encoding="utf-8");tmp.replace(path);return path,stats
