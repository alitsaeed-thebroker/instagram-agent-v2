"""Application entry point for PDF-to-Markdown and knowledge extraction."""

from __future__ import annotations

from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")


from src.department3.legacy_live import run_legacy_strategy_advisory, run_legacy_visual_opportunity_compat, run_legacy_creative_compat

from src.department3.planning_cutover import cutover_legacy_planning_products, PLANNING_CUTOVER_VERSION, PlanningNoContentError
from src.planning.engine import VERSION as PLANNING_ENGINE_VERSION

from src.department3.live_orchestration import LiveDepartment3Orchestrator, quarantine_legacy_result
from src.department3.runtime_guard import assert_noncanonical_output

import sys
import json
import argparse
import re
import time
import os
from datetime import datetime, timezone
from pathlib import Path

from pypdf.errors import PdfReadError

from src.ai.agents.knowledge_agent import KnowledgeAgent
from src.ai.agents.marketing_strategy_agent import MarketingStrategyAgent
from src.ai.agents.content_planner import ContentPlanner
from src.ai.agents.creative_director_agent import CreativeDirectorAgent
from src.ai.agents.scene_planner import ScenePlanner
from src.ai.agents.shot_planner import ShotPlanner
from src.ai.agents.asset_intelligence_agent import AssetIntelligenceAgent
from src.content.schema import ContentPlan
from src.content.inventory import INVENTORY_VERSION, load_content_opportunity_inventory
from src.scenes.schema import ScenePlanCollection
from src.core.file_manager import ProjectInput, find_project_inputs
from src.core.document_analysis import analyze_document, save_document_analysis
from src.core.logger import get_logger
from src.core.console import configure_utf8_console
from src.core.markdown_writer import save_markdown
from src.core.pdf_reader import extract_text_from_pdf
from src.core.text_document_reader import extract_text_document, save_extracted_text
from src.knowledge.evaluator import KnowledgeEvaluator
from src.knowledge.document_classifier import DocumentClassifier, DocumentType
from src.knowledge.fusion import fuse_knowledge, FUSION_VERSION
from src.knowledge.schema import ProjectKnowledge
from src.knowledge.audit import audit_project
from src.knowledge.storage import save_project_knowledge
from src.knowledge.deep_source import analyze_deep_source, MODULE_VERSION as DEEP_SOURCE_VERSION, SCHEMA_VERSION as DEEP_SOURCE_SCHEMA_VERSION
from src.knowledge.commercial import extract_document_intelligence
from src.department1 import Department1Pipeline, Department1Error
from src.department1.pipeline import project_storage_key
from src.knowledge.handoff import (
    Department2HandoffError,
    load_department2_handoff,
    write_source_markdown,
)
from src.image_processing.planner import ImageProcessingPlanner
from src.image_prompts import ImagePromptGenerator
from src.production import ProductionWorkflow, DetailPreservationEnhancer
from src.branding import BrandComposer
from src.creative.visual_art_director import VisualArtDirectorWorkflow
from src.branding.source_content import generate_branded_content, MODULE_VERSION as BRANDED_CONTENT_VERSION, SCHEMA_VERSION as BRANDED_CONTENT_SCHEMA_VERSION
from src.hardening import HardeningPipeline, run_health_check
from src.post_package import PostPackagePipeline
from src.utils.config import (INPUT_DIRECTORY, KNOWLEDGE_OUTPUT_DIRECTORY, MARKDOWN_OUTPUT_DIRECTORY, PROJECT_ROOT,
    REPORTS_OUTPUT_DIRECTORY, CONTENT_OUTPUT_DIRECTORY, CAMPAIGNS_OUTPUT_DIRECTORY,
    CREATIVE_DIRECTIONS_OUTPUT_DIRECTORY, VISUAL_DIRECTIONS_OUTPUT_DIRECTORY, SCENE_PLANS_OUTPUT_DIRECTORY, SHOT_PLANS_OUTPUT_DIRECTORY,
    IMAGE_PROCESSING_PLANS_OUTPUT_DIRECTORY, IMAGE_PROMPTS_OUTPUT_DIRECTORY,
    ASSET_INTELLIGENCE_OUTPUT_DIRECTORY, VISUAL_OPPORTUNITIES_OUTPUT_DIRECTORY, CREATIVE_INTELLIGENCE_OUTPUT_DIRECTORY,
    CONTENT_INVENTORY_OUTPUT_DIRECTORY,
    STRATEGY_OUTPUT_DIRECTORY, PRODUCED_IMAGES_OUTPUT_DIRECTORY, DETAIL_ENHANCED_OUTPUT_DIRECTORY,
    PRODUCTION_MANIFESTS_OUTPUT_DIRECTORY, IMAGE_QA_OUTPUT_DIRECTORY, REVIEW_OUTPUT_DIRECTORY,
    SELECTED_IMAGES_OUTPUT_DIRECTORY, SOURCE_IMAGE_RANKING_OUTPUT_DIRECTORY)
from src.visual_assets.analysis import analyze_visual_assets
from src.visual_assets.extraction import extract_visual_assets, verify_source_integrity
from src.visual_assets.selection import assert_selection_ready, plan_asset_selection
from src.visual_assets.ranking import rank_source_images, MODULE_VERSION as RANKING_VERSION, SCHEMA_VERSION as RANKING_SCHEMA_VERSION
from src.planning import PlanningEngine, VisualOpportunityEngine
from src.creative_intelligence import RealEstateCreativeIntelligence
from src.campaign_intelligence import CampaignIntelligenceEngine
from src.planning.creative_reviewer import RealEstateCreativeReviewer, REVIEWER_VERSION
from src.execution import (EARLIEST_PLATFORM_DEPENDENT_STAGE, PLATFORM_DEPENDENT_STAGES,
                           PLATFORM_INDEPENDENT_STAGES, STAGE_ORDER, StageCache,
                           StageSelection, ancestors, select_stages)
from src.execution.stages import DEPENDENCIES, sha256_file
from src.brand_kit import (approve_brand, ensure_brand_analysis, run_brand_identity_analyzer, run_brand_kit_analysis,
                           run_brand_readiness_validator)
from src.brand_kit.project_identity import extract_project_brand_identity, MODULE_VERSION as PROJECT_BRAND_VERSION, SCHEMA_VERSION as PROJECT_BRAND_SCHEMA_VERSION
from src.social_review import SocialContentReview
from src.social_review.dashboard import DUPLICATE_DETECTION_VERSION, REVIEW_VERSION
from src.publishing import (CloudflareR2MediaHost, MediaHostingError, MetaInstagramAdapter,
                            PublishingFoundation, ControlledPublishError, controlled_publish,
                            list_publishable, run_media_hosting)
from src.publishing.meta import meta_status
from src.publishing.ledger import PublicationLedger
from src.reset import ProjectResetError, reset_project_derived_state
from src.publishing.worker import WorkerState, run_worker
from src.publishing.windows_scheduler import (WindowsTaskSchedulerAdapter, install_worker,
                                               scheduler_status, worker_config)


logger = get_logger(__name__)
_RUN_ACCOUNTING: list[dict[str, Any]] = []
_STAGE_DISPLAY_NAMES={"visual-art-director":"Visual Art Director","creative-visual-qa":"Creative Visual QA","branded-image-qa":"Branded Image QA","image-output-qa":"Image Output QA","self-correction":"Self Correction","provenance-audit":"Provenance Audit","production-quality-report":"Production Quality Report","release-manager":"Release Manager","brand-composer":"Brand Composer","content-grouping-analyzer":"Content Grouping Analyzer","caption-generator":"Caption Generator","hashtag-generator":"Hashtag Generator","alt-text-generator":"Alt Text Generator","post-package-builder":"Post Package Builder","post-package-qa":"Post Package QA","social-content-review":"Social Content Review"}
_REQUESTED_LANGUAGES=("en",)
_PLATFORM_STRATEGY="both_platform_optimized"
_PUBLISH_TARGET="use_planned"
_PLATFORM_STRATEGY_SOURCE="default"
_PLATFORM_STRATEGY_REQUESTED=False
BRANDED_CONTENT_CACHE_MODE="complete-content-plan-dynamic-renderability-v1"
BRANDED_CONTENT_RUN_DESCRIPTION="[RUN] Branded Content — consuming complete content plan; no AI or Meta requests"


def _stage_display_name(stage: str) -> str:
    return _STAGE_DISPLAY_NAMES.get(stage,stage.replace("-"," ").title())
BRAND_STAGE_ORDER = ("brand-kit-analysis", "brand-identity-analyzer", "brand-readiness-validator")
CLI_STAGE_ORDER = (*BRAND_STAGE_ORDER, "media-hosting", *STAGE_ORDER)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the source-only marketing pipeline with dependency-aware caching.")
    parser.add_argument("--project")
    parser.add_argument("--stage", choices=CLI_STAGE_ORDER)
    parser.add_argument("--from-stage", choices=STAGE_ORDER)
    parser.add_argument("--force-stage", choices=CLI_STAGE_ORDER)
    parser.add_argument("--force-all", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--list-stages", action="store_true")
    parser.add_argument("--brand-status", action="store_true")
    parser.add_argument("--approve-brand", action="store_true")
    parser.add_argument("--health-check", action="store_true")
    parser.add_argument("--regression-check", action="store_true")
    parser.add_argument("--knowledge-audit", action="store_true", help="Read-only source-to-knowledge completeness audit")
    parser.add_argument("--language",choices=("en","ar","ku"))
    parser.add_argument("--languages")
    parser.add_argument("--publish-dry-run",action="store_true")
    parser.add_argument("--show-publishing-queue",action="store_true")
    parser.add_argument("--publish-meta",action="store_true")
    parser.add_argument("--meta-status",action="store_true")
    parser.add_argument("--media-host-status",action="store_true")
    parser.add_argument("--publish-one")
    parser.add_argument("--publish-one-package")
    parser.add_argument("--confirm-real-publish",action="store_true")
    parser.add_argument("--list-publishable",action="store_true")
    parser.add_argument("--platform-strategy",choices=("instagram_only","facebook_only","both_mirrored","both_platform_optimized"))
    parser.add_argument("--publish-target",choices=("instagram","facebook","both","use_planned"),default="use_planned")
    parser.add_argument("--publishing-reconcile",action="store_true")
    parser.add_argument("--reconcile-dry-run",action="store_true")
    parser.add_argument("--publishing-worker",action="store_true")
    parser.add_argument("--install-publishing-worker",action="store_true")
    parser.add_argument("--uninstall-publishing-worker",action="store_true")
    parser.add_argument("--publishing-worker-status",action="store_true")
    parser.add_argument("--pause-publishing-worker",action="store_true")
    parser.add_argument("--resume-publishing-worker",action="store_true")
    parser.add_argument("--dry-run",action="store_true")
    parser.add_argument("--reset-project-derived-state",action="store_true")
    parser.add_argument("--confirm-reset",action="store_true")
    return parser.parse_args(argv)


def _resolve_platform_strategy(cli_value: str | None) -> tuple[str, str]:
    """Resolve strict CLI > project configuration > default precedence."""
    if cli_value is not None:
        return cli_value, "cli"
    config_path=PROJECT_ROOT/"input"/"platform-strategy.json"
    if config_path.is_file():
        value=json.loads(config_path.read_text(encoding="utf-8"))
        configured=value.get("platform_strategy")
        allowed={"instagram_only","facebook_only","both_mirrored","both_platform_optimized"}
        if configured not in allowed:
            raise ValueError(f"Invalid platform_strategy in {config_path}: {configured!r}")
        return configured,"config"
    return "both_platform_optimized","default"


def main(argv: list[str] | None = None) -> int:
    """Run the PDF extraction workflow and return a process exit code."""
    configure_utf8_console()
    args = _parse_args(argv)
    if args.confirm_reset and not args.reset_project_derived_state:
        logger.error("--confirm-reset requires --reset-project-derived-state.");return 2
    if args.reset_project_derived_state:
        if not args.project:
            logger.error("--reset-project-derived-state requires --project.");return 2
        try:
            result=reset_project_derived_state(PROJECT_ROOT,args.project,confirm=args.confirm_reset)
            print("Project Derived State Reset")
            print(json.dumps(result,indent=2,ensure_ascii=False))
            if not args.confirm_reset:print("Dry run only. Re-run with --confirm-reset to execute.")
            return 0
        except (ProjectResetError,OSError,ValueError) as error:
            logger.error("Project reset failed: %s",error);return 1
    worker_modes=(args.publishing_worker,args.install_publishing_worker,args.uninstall_publishing_worker,
                  args.publishing_worker_status,args.pause_publishing_worker,args.resume_publishing_worker)
    if sum(bool(value) for value in worker_modes)>1:
        logger.error("Select only one publishing worker operation.");return 2
    if args.dry_run and not (args.publishing_worker or args.install_publishing_worker):
        logger.error("--dry-run is supported with --publishing-worker or --install-publishing-worker.");return 2
    if any(worker_modes):
        try:
            if args.publishing_worker:
                result=run_worker(PROJECT_ROOT,dry_run=args.dry_run);print(json.dumps(result,indent=2,ensure_ascii=False));return int(result["exit_code"])
            if args.install_publishing_worker:
                result=install_worker(PROJECT_ROOT,dry_run=args.dry_run);print(json.dumps(result,indent=2,ensure_ascii=False));return 0
            config=worker_config(PROJECT_ROOT);adapter=WindowsTaskSchedulerAdapter();state=WorkerState(PROJECT_ROOT)
            if args.publishing_worker_status:
                print(json.dumps(scheduler_status(PROJECT_ROOT,adapter),indent=2,ensure_ascii=False));return 0
            if args.pause_publishing_worker:
                state.set_enabled(False)
                if os.name=="nt":adapter.set_enabled(config["task_name"],False)
                print(json.dumps({"task_name":config["task_name"],"worker_enabled":False,"meta_publication_writes":0},indent=2));return 0
            if args.resume_publishing_worker:
                state.set_enabled(True)
                if os.name=="nt":adapter.set_enabled(config["task_name"],True)
                print(json.dumps({"task_name":config["task_name"],"worker_enabled":True,"meta_publication_writes":0},indent=2));return 0
            result=adapter.uninstall(config["task_name"]) if os.name=="nt" else {"installed":False,"task_name":config["task_name"]}
            print(json.dumps({**result,"publication_truth_preserved":True,"meta_publication_writes":0},indent=2));return 0
        except (OSError,ValueError,RuntimeError) as error:
            logger.error("Publishing worker operation failed: %s",error);return 1
    controlled_count=sum(bool(x) for x in (args.publish_one,args.publish_one_package))
    if controlled_count>1:logger.error("Use either --publish-one or --publish-one-package, not both.");return 2
    if args.confirm_real_publish and controlled_count!=1:logger.error("--confirm-real-publish requires an explicit --publish-one or --publish-one-package selection.");return 2
    global _PLATFORM_STRATEGY, _PUBLISH_TARGET, _PLATFORM_STRATEGY_SOURCE, _PLATFORM_STRATEGY_REQUESTED
    raw_argv=list(argv) if argv is not None else sys.argv[1:]
    _PLATFORM_STRATEGY_REQUESTED="--platform-strategy" in raw_argv
    _PLATFORM_STRATEGY,_PLATFORM_STRATEGY_SOURCE=_resolve_platform_strategy(args.platform_strategy)
    _PUBLISH_TARGET = args.publish_target
    if _PLATFORM_STRATEGY_REQUESTED and not any((args.stage,args.from_stage,args.force_stage,args.force_all,args.resume,args.publish_dry_run,args.publish_meta)):
        args.from_stage=EARLIEST_PLATFORM_DEPENDENT_STAGE
    if args.publish_dry_run:
        if args.stage or args.from_stage or args.force_stage or args.force_all:logger.error("--publish-dry-run cannot be combined with stage selection.");return 2
        args.from_stage="publishing-queue"
    if args.publish_meta:
        if args.stage or args.from_stage or args.force_stage or args.force_all or args.publish_dry_run:logger.error("--publish-meta cannot be combined with other execution modes.");return 2
        if not args.project:logger.error("--publish-meta requires --project to preserve the one-transaction invocation boundary.");return 2
    if (args.stage=="meta-platform-adapter" or args.force_stage=="meta-platform-adapter" or args.from_stage=="meta-platform-adapter") and not args.project:
        logger.error("Real Meta execution requires --project to preserve the one-transaction invocation boundary.");return 2
    global _REQUESTED_LANGUAGES
    if args.language and args.languages:logger.error("Use either --language or --languages, not both.");return 2
    requested_languages=tuple(x.strip() for x in args.languages.split(",") if x.strip()) if args.languages else (args.language or "en",)
    if any(x not in {"en","ar","ku"} for x in requested_languages):logger.error("Languages must use en, ar, or ku.");return 2
    _REQUESTED_LANGUAGES=requested_languages
    _RUN_ACCOUNTING.clear()
    if args.list_stages:
        for name in CLI_STAGE_ORDER: print(name)
        return 0
    if args.meta_status:
        try:
            status=meta_status(PROJECT_ROOT);safe=lambda value:str(value or "Not configured").encode("ascii","backslashreplace").decode();ig=status["instagram"];fb=status["facebook"];both=status["combined"];ig_permissions="validated" if str(ig.get("permission_validation",{}).get("status","")).startswith("validated") else "Not validated";print("Meta Publishing Status\n\nProvider: Meta");print(f"Adapter enabled: {status['adapter_enabled']}");print(f"\nInstagram\n- configured: {ig['configured']}\n- authentication mode: {safe(ig.get('authentication_mode'))}\n- account: {safe(ig.get('instagram_username') or ig.get('instagram_account_id'))}\n- token configured: {status['token_configured']}\n- token valid: {ig.get('token_valid',False)}\n- permissions: {ig_permissions}\n- credentials valid: {ig.get('credentials_valid',False)}\n- publishing ready: {ig['publishing_ready']}");print(f"\nFacebook\n- configured: {fb['configured']}\n- authentication mode: {safe(fb.get('authentication_mode'))}\n- page: {safe(fb.get('page_id'))}\n- token configured: {fb['token_configured']}\n- token valid: {fb['token_valid']}\n- permissions: {', '.join(fb.get('permissions',[])) or 'Not validated'}\n- credentials valid: {fb.get('credentials_valid',False)}\n- publishing ready: {fb['publishing_ready']}");print(f"\nCombined\n- instagram ready: {both['instagram_ready']}\n- facebook ready: {both['facebook_ready']}\n- both ready: {both['both_ready']}\n- partial publishing supported: {both['partial_publishing_supported']}");return 0
        except (OSError,ValueError) as error:logger.error("Meta status failed: %s",error);return 1
    if args.media_host_status:
        status=CloudflareR2MediaHost(PROJECT_ROOT).status()
        print("Media Hosting Status\n\nProvider: Cloudflare R2")
        print(f"\n- configured: {status['configured']}\n- bucket: {status['bucket']}\n- endpoint configured: {status['endpoint_configured']}\n- public base URL configured: {status['public_base_url_configured']}\n- credentials present: {status['credentials_present']}\n- bucket access: {status['bucket_access']}\n- public delivery: {status['public_delivery']}\n- ready: {status['ready']}")
        for warning in status.get("warnings",[]): print(f"- warning: {warning}")
        return 0 if status["ready"] else 1
    if args.health_check:
        try:
            path=run_health_check(PROJECT_ROOT,args.project)
            report=json.loads(path.read_text(encoding="utf-8"))
            if args.project:
                console_project=args.project.encode("ascii","backslashreplace").decode("ascii")
                logger.info("System Health Check\n\nProject: %s",console_project)
                for name,status in report["checks"].items():logger.info("%s: %s",name.replace("_"," ").title(),status)
                logger.info("Health Score: %d/100\nStatus: %s",report["health_score"],report["status"])
            else:logger.info("System Health Check\nStatus: %s\nProjects checked: %d",report["status"],len(report["projects"]))
            return 0 if report["status"] in {"HEALTHY","HEALTHY_WITH_WARNINGS"} else 1
        except (OSError,ValueError) as error:logger.error("Health check failed: %s",error);return 1
    if args.regression_check:
        import subprocess
        return subprocess.run([sys.executable,"-m","unittest","discover","-s","tests/regression"],cwd=PROJECT_ROOT).returncode
    if args.brand_status:
        return _run_brand_readiness(approve=False)
    if args.approve_brand:
        return _run_brand_readiness(approve=True)
    if args.stage == "brand-kit-analysis" or args.force_stage == "brand-kit-analysis":
        return _run_global_brand_kit(force=args.force_stage == "brand-kit-analysis" or args.force_all)
    if args.stage in {"brand-identity-analyzer", "brand-readiness-validator"} or args.force_stage in {"brand-identity-analyzer", "brand-readiness-validator"}:
        return _run_brand_readiness(approve=False, identity_only=(args.stage or args.force_stage) == "brand-identity-analyzer", force=args.force_all or args.force_stage == "brand-identity-analyzer")
    logger.info("Searching for project folders and PDFs...")
    try:
        projects = find_project_inputs(INPUT_DIRECTORY)
    except (FileNotFoundError, NotADirectoryError, PermissionError) as error:
        logger.error("Error: %s", error)
        return 1
    except OSError as error:
        logger.error("Error while reading the input folder: %s", error)
        return 1

    if not projects:
        logger.info("No PDF files were found inside the input folder.")
        return 0

    if args.project:
        selected = _select_project(projects, args.project)
        if selected is None:
            logger.error("Project '%s' was not found. Available projects: %s", args.project, ", ".join(p.name for p in projects))
            return 2
        projects = [selected]
    if args.knowledge_audit:
        if not args.project:
            logger.error("--knowledge-audit requires --project.")
            return 2
        try:
            human, machine, report = audit_project(projects[0].name, PROJECT_ROOT)
            print(human.read_text(encoding="utf-8"))
            print(f"Machine-readable report: {machine}\nMeta write requests: 0")
            return 0
        except (OSError, ValueError) as error:
            logger.error("Knowledge audit failed: %s", error)
            return 1
    if args.publishing_reconcile:
        if not args.project:logger.error("--publishing-reconcile requires --project.");return 2
        try:
            ledger=PublicationLedger(PROJECT_ROOT);adapter=MetaInstagramAdapter(PROJECT_ROOT);account=adapter.validate_credentials(persist=not args.reconcile_dry_run)
            if account.get("status")!="ready":raise RuntimeError("Read-only Meta reconciliation requires a validated matching Instagram account")
            results=[]
            for record in ledger.records(project_id=projects[0].name):
                if record["state"] in {"PUBLISHING_UNCERTAIN","RECONCILIATION_REQUIRED"}:results.append(ledger.reconcile_publication(record["publication_identity"],adapter,dry_run=args.reconcile_dry_run))
            report={"project_id":projects[0].name,"dry_run":args.reconcile_dry_run,"results":results,"meta_publication_writes":0,"ledger_status":ledger.status()};print(json.dumps(report,indent=2,ensure_ascii=False));return 0
        except (OSError,ValueError,RuntimeError) as error:logger.error("Publishing reconciliation failed: %s",error);return 1
    if args.list_publishable or controlled_count:
        if not args.project:logger.error("Controlled publishing commands require --project.");return 2
        try:
            if args.list_publishable:
                rows=list_publishable(PROJECT_ROOT,projects[0].name);print("Selectable Publication Items")
                print("queue_item_id | package_id | platform | type | images | status | real | caption")
                for row in rows:print(f"{row['queue_item_id']} | {row['package_id']} | {row['platform']} | {row['package_type']} | {row['image_count']} | {row['status']} | {row['real_publication_status']} | {row['caption_summary']}")
                print(f"\nSelectable items: {len(rows)}\nMeta write requests: 0");return 0
            result=controlled_publish(PROJECT_ROOT,projects[0].name,queue_item_id=args.publish_one,package_id=args.publish_one_package,confirm=args.confirm_real_publish)
            if result["status"]=="already_published":
                receipt=result["receipt"];print(f"Controlled Publish Result\n\n- Status: already_published\n- Instagram media ID: {receipt.get('published_media_id')}\n- Receipt ID: {receipt.get('receipt_id')}\n- Meta write requests: 0");return 0
            preview=result["preview"];print("Controlled Publish Preview")
            labels=(("project","Project"),("queue_item_id","Queue item ID"),("package_id","Package ID"),("platform","Platform"),("package_type","Package type"),("image_count","Number of images"),("caption_length","Caption length"),("hashtag_count","Hashtag count"),("hosted_media_urls_verified","Hosted media URLs verified"),("r2_provider_ready","R2 provider ready"),("meta_credentials_ready","Meta credentials ready"),("existing_real_receipt","Existing real receipt"),("idempotency_key_present","Idempotency key present"),("immediate_publish_override","Immediate publish override"))
            for key,label in labels:print(f"- {label}: {preview[key]}")
            if result["status"]=="preview":print("- Confirmation: not supplied; no publication performed\n- Meta write requests: 0");return 0
            receipt=result["receipt"];print(f"\nControlled Publish Result\n\n- Status: PUBLISHED\n- Platform: Instagram\n- Package ID: {receipt['package_id']}\n- Queue item ID: {receipt['queue_item_id']}\n- Instagram media ID: {receipt['published_media_id']}\n- Published at: {receipt['published_at']}\n- Receipt ID: {receipt['receipt_id']}\n- Idempotency protected: True\n- Other queue items modified: 0");return 0
        except (OSError,ValueError,ControlledPublishError) as error:logger.error("Controlled publish blocked: %s",error);return 1
    if args.stage == "media-hosting" or args.force_stage == "media-hosting":
        failures=[]
        for project in projects:
            try:
                path,stats=run_media_hosting(PROJECT_ROOT,project.name)
                logger.info("Media Hosting: project=%s eligible=%d uploaded=%d reused=%d failed=%d verified=%d manifest=%s Meta write requests=0",project.name,stats["eligible"],stats["uploaded"],stats["reused"],stats["failed"],stats["verified_public_urls"],path)
                if stats["failed"]: failures.append(project.name)
            except (OSError,ValueError,MediaHostingError) as error:
                logger.error("Media hosting failed for %s: %s",project.name,error);failures.append(project.name)
        return 1 if failures else 0
    started = time.monotonic()
    if args.show_publishing_queue:
        if not args.project:logger.error("--show-publishing-queue requires --project.");return 2
        try:print(PublishingFoundation(args.project,PROJECT_ROOT).show_queue().encode("ascii","backslashreplace").decode());return 0
        except (OSError,ValueError) as error:logger.error("Unable to show publishing queue: %s",error);return 1
    if args.publish_meta:args.from_stage="meta-platform-adapter"
    planning_modes = {"visual-opportunities", "campaign-planner", "content-planner", "creative-director", "scene-planner", "shot-planner", "image-processing-planner", "image-prompt-generator", "detail-preservation-enhancer", "deterministic-image-processor", "image-output-qa", "visual-art-director", "brand-composer", "branded-image-qa", "creative-visual-qa", "self-correction", "provenance-audit", "production-quality-report", "release-manager", "content-grouping-analyzer", "caption-generator", "hashtag-generator", "alt-text-generator", "post-package-builder", "post-package-qa", "social-content-review", "publishing-queue", "scheduling-engine", "publish-preflight", "mock-platform-adapter", "meta-platform-adapter", "publication-manifest", "production-manifest", "review-gallery"}
    requested_start = args.stage or args.from_stage or args.force_stage
    use_staged_planning = bool(_PLATFORM_STRATEGY_REQUESTED or requested_start in planning_modes or requested_start in {"asset-intelligence","deep-source-analysis","source-image-ranking","project-brand-identity","branded-content"} or (args.resume and any(_existing_manifest(p.name) for p in projects)))
    failures = _process_independent_projects(projects, args, use_staged_planning)
    if failures:
        logger.error("Processing failed for: %s", ", ".join(failures).encode("ascii","backslashreplace").decode())
        return 1
    if use_staged_planning and len(_RUN_ACCOUNTING)>1:
        totals={key:sum(int(item.get(key,0)) for item in _RUN_ACCOUNTING) for key in ("stages_executed","stages_skipped_cached","prerequisites_reused","stages_not_requested","stages_failed","stages_blocked","api_calls_executed","api_calls_avoided_by_cache","api_calls_failed","api_calls_retried")}
        logger.info("Global Execution Summary:\n- Projects processed: %d\n- Stages run: %d\n- Stages skipped from cache: %d\n- Valid prerequisites reused: %d\n- Stages not requested: %d\n- Failed stages: %d\n- Blocked stages: %d\n- API calls executed: %d\n- API calls avoided by cache: %d\n- API calls failed: %d\n- API calls retried: %d\n- Total wall-clock duration: %.2fs",
                    len(projects),totals["stages_executed"],totals["stages_skipped_cached"],totals["prerequisites_reused"],totals["stages_not_requested"],totals["stages_failed"],totals["stages_blocked"],totals["api_calls_executed"],totals["api_calls_avoided_by_cache"],totals["api_calls_failed"],totals["api_calls_retried"],time.monotonic()-started)
    elif not use_staged_planning and not _RUN_ACCOUNTING:
        logger.info("Execution Summary:\n- Projects processed: %d\n- Failed stages: %d\n- Total duration: %.2fs", len(projects), len(failures), time.monotonic()-started)
    logger.info("Done.")
    return 0


def _process_independent_projects(projects, args, use_staged_planning):
    """A project failure must never prevent independent projects from running."""
    failures = []
    for project in projects:
        try:
            successful = (_process_staged_planning(project, args) if use_staged_planning
                          else _process_default_cached(project, args))
        except Exception:
            logger.exception("Project processing failed: %s", project.name)
            successful = False
        if not successful:
            failures.append(project.name)
    return failures


def _run_global_brand_kit(*, force: bool = False) -> int:
    logger.info("[RUN] Brand Kit Analysis")
    logger.info("Reading Domus Erbil brand configuration...")
    logger.info("Scanning official logo files...")
    logger.info("Validating brand configuration...")
    try:
        result = run_brand_kit_analysis(PROJECT_ROOT, force=force)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        logger.error("Brand Kit Analysis failed: %s", error)
        return 1
    if result.cached:
        logger.info("[SKIP] Brand Kit Analysis - valid cached artifact")
        return 0
    summary = result.inventory["summary"]
    preferred = result.inventory.get("preferred_logo_id") or "none"
    config = json.loads(result.config_path.read_text(encoding="utf-8"))
    colors = config["visual_identity"]["colors"].get("status", "unconfirmed")
    font_status = config["visual_identity"]["typography"].get("status", "missing").replace("_", " ")
    logger.info(
        "Brand Kit Analysis completed:\n- Logo files found: %d\n- Usable logos: %d\n- Preferred logo: %s\n- Brand colors: %s\n- Fonts: %s\n- Configuration status: %s",
        summary["files_found"], summary["usable_logos"], preferred, colors, font_status, result.validation.status,
    )
    if not result.inventory["logos"]:
        logger.warning("Brand Kit warning:\nNo official Domus Erbil logo was found in input/brand/logos/.\nAdd an approved SVG or transparent PNG before running Brand Composer.")
    for error in result.validation.errors: logger.error("Brand configuration error: %s", error)
    return 0 if result.validation.valid else 1


def _run_brand_readiness(*, approve: bool, identity_only: bool = False, force: bool = False) -> int:
    try:
        kit = run_brand_kit_analysis(PROJECT_ROOT, force=force)
        if not kit.validation.valid:
            for error in kit.validation.errors: logger.error("Brand configuration error: %s", error)
            return 1
        logger.info("[RUN] Brand Identity Analyzer")
        logger.info("Reading preferred official logo...\nExtracting significant logo colors...\nBuilding production-safe palette...\nConfiguring typography system...")
        identity_result = run_brand_identity_analyzer(PROJECT_ROOT, force=force)
        identity = identity_result.identity; palette = identity["palette"]
        if identity_result.cached: logger.info("[SKIP] Brand Identity Analyzer - valid cached artifact")
        else: logger.info("Brand identity analysis saved:\n%s", identity_result.path.relative_to(PROJECT_ROOT).as_posix())
        logger.info("Brand Identity Analyzer completed:\n- Preferred logo: %s\n- Significant logo colors: %d\n- Primary color: %s\n- Secondary color: %s\n- Accent: %s\n- Typography: system-selected\n- RTL support: ready",
                    identity.get("preferred_logo", {}).get("filename", "none"), len(palette.get("logo_colors", [])),
                    (palette.get("primary") or {}).get("hex", "missing"), (palette.get("secondary") or {}).get("hex", "missing"), (palette.get("accent") or {}).get("hex", "missing"))
        if identity_only: return 0 if identity.get("identity_status") != "blocked" else 1
        logger.info("[RUN] Brand Readiness Validator")
        readiness = run_brand_readiness_validator(PROJECT_ROOT)
        report = readiness.report
        if approve:
            for warning in report["warnings"]: logger.warning("Brand approval warning: %s", warning)
            readiness = approve_brand(PROJECT_ROOT); report = readiness.report
            logger.info("Brand approved and locked. Approved config hash: %s", report["approval"].get("approved_config_hash"))
        company = json.loads((PROJECT_ROOT/"input"/"brand"/"brand-config.json").read_text(encoding="utf-8"))["company"]
        logger.info("Brand Readiness:\n- Official identity: %s\n- Logo: %s\n- Colors: %s\n- Typography: system-selected\n- Website: %s\n- Phone: %s\n- Email: %s\n- RTL support: ready\n- Status: %s\n- Score: %d/100",
                    "ready" if not any("name" in x for x in report["blocking_issues"]) else "blocked", "ready" if identity.get("preferred_logo", {}).get("valid") else "blocked",
                    json.loads((PROJECT_ROOT/"input"/"brand"/"brand-config.json").read_text(encoding="utf-8"))["visual_identity"]["colors"]["status"],
                    "confirmed" if company.get("website") else "blocked", "confirmed" if company.get("phone_numbers") else "missing optional", "confirmed" if company.get("email_addresses") else "missing optional",
                    report["readiness_status"].upper(), report["score"])
        return 0 if report["readiness_status"] in {"ready", "ready_with_warnings"} else 1
    except (OSError, ValueError, json.JSONDecodeError) as error:
        logger.error("Brand readiness failed: %s", error)
        return 1


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _select_project(projects: list[ProjectInput], requested: str) -> ProjectInput | None:
    exact = next((p for p in projects if p.name == requested), None)
    if exact: return exact
    matches = [p for p in projects if _slug(p.name) == _slug(requested)]
    return matches[0] if len(matches) == 1 else None


def _existing_manifest(project: str) -> bool:
    from src.utils.config import MANIFESTS_OUTPUT_DIRECTORY
    return (MANIFESTS_OUTPUT_DIRECTORY / f"{project}-run-manifest.json").exists()


def _process_default_cached(project: ProjectInput, args: argparse.Namespace) -> bool:
    """Run the complete safe pipeline; never infer per-stage success from project success."""
    started_at=time.monotonic()
    from src.utils.config import OUTPUT_DIRECTORY
    cache = StageCache(project.name, [*project.pdf_files, *project.image_files, *project.auxiliary_files])
    cache.reset_runtime_accounting(requested_mode="force_all" if args.force_all else "default",requested_stage=None,stage_forced=args.force_all)
    success = _process_project(project)
    if not success:
        cache.fail("discover", "Core project processing failed");_finish_early_accounting(project.name,cache,started_at,preserve=False);return False
    downstream_args = argparse.Namespace(**vars(args))
    downstream_args.from_stage = "deep-source-analysis"
    downstream_args.stage = None
    downstream_args.force_stage = None
    downstream_args.force_all = False
    downstream_args.resume = False
    downstream_args.publish_meta = False
    downstream_args.default_continuation = True
    return _process_staged_planning(project, downstream_args)


def _artifact(directory: Path, project: str, suffix: str) -> Path | None:
    exact = directory / f"{project}{suffix}.json"
    if exact.exists(): return exact
    candidates = sorted(directory.glob(f"*{suffix}.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    normalized = _slug(project)
    return next((p for p in candidates if _slug(p.stem) == _slug(f"{project}{suffix}")), None)


def _ranking_folder(project: str) -> str:
    return re.sub(r"[^\w.-]+", "-", project, flags=re.UNICODE).strip("-.") or "project"


def _read_count(path: Path, key: str) -> int:
    return len(json.loads(path.read_text(encoding="utf-8")).get(key,[]))


def _process_staged_planning(project: ProjectInput, args: argparse.Namespace) -> bool:
    """Fast path for the currently iterated planning stages; upstream artifacts are immutable inputs."""
    started_at=time.monotonic()
    from src.utils.config import (ASSET_INTELLIGENCE_OUTPUT_DIRECTORY, CONTENT_OUTPUT_DIRECTORY,
        CREATIVE_DIRECTIONS_OUTPUT_DIRECTORY, IMAGE_PROCESSING_PLANS_OUTPUT_DIRECTORY,
        SCENE_PLANS_OUTPUT_DIRECTORY, SHOT_PLANS_OUTPUT_DIRECTORY, SOURCE_IMAGES_OUTPUT_DIRECTORY,
        STRATEGY_OUTPUT_DIRECTORY, VISUAL_INVENTORY_OUTPUT_DIRECTORY, VISUAL_OPPORTUNITIES_OUTPUT_DIRECTORY)
    selection = select_stages(stage=args.stage, from_stage=args.from_stage, force_stage=args.force_stage, force_all=args.force_all)
    if getattr(args,"default_continuation",False):
        selection=StageSelection(tuple(stage for stage in STAGE_ORDER[STAGE_ORDER.index("deep-source-analysis"):] if stage not in {"branded-content","meta-platform-adapter"}),frozenset())
    if args.publish_meta:selection=StageSelection(("publishing-queue","scheduling-engine","publish-preflight","meta-platform-adapter","publication-manifest"),frozenset())
    elif args.from_stage=="meta-platform-adapter":selection=StageSelection(("meta-platform-adapter","publication-manifest"),selection.forced)
    # Phase 20B's QA stage creates its own branded manifest and review gallery.
    # Do not rerun the separate completed unbranded finalization stages.
    if args.from_stage == "brand-composer":
        selection = StageSelection(("visual-art-director", "brand-composer", "image-output-qa", "branded-image-qa", "creative-visual-qa", "self-correction", "provenance-audit", "production-quality-report", "release-manager","content-grouping-analyzer","caption-generator","hashtag-generator","alt-text-generator","post-package-builder","post-package-qa","social-content-review"), selection.forced)
    elif args.from_stage == "branded-image-qa":
        selection = StageSelection(("branded-image-qa", "creative-visual-qa", "self-correction", "provenance-audit", "production-quality-report", "release-manager","content-grouping-analyzer","caption-generator","hashtag-generator","alt-text-generator","post-package-builder","post-package-qa","social-content-review"), selection.forced)
    elif args.from_stage in {"creative-visual-qa","self-correction","provenance-audit","production-quality-report","release-manager"}:
        hardening_order=("creative-visual-qa","self-correction","provenance-audit","production-quality-report","release-manager","content-grouping-analyzer","caption-generator","hashtag-generator","alt-text-generator","post-package-builder","post-package-qa","social-content-review")
        selection = StageSelection(hardening_order[hardening_order.index(args.from_stage):], selection.forced)
    elif args.from_stage in {"content-grouping-analyzer","caption-generator","hashtag-generator","alt-text-generator","post-package-builder","post-package-qa","social-content-review"}:
        package_order=("content-grouping-analyzer","caption-generator","hashtag-generator","alt-text-generator","post-package-builder","post-package-qa","social-content-review")
        selection=StageSelection(package_order[package_order.index(args.from_stage):],selection.forced)
    cache = StageCache(project.name, [*project.pdf_files, *project.image_files, *project.auxiliary_files])
    strategy_artifact=_persist_platform_strategy(project.name,_PLATFORM_STRATEGY,_PLATFORM_STRATEGY_SOURCE)
    if _PLATFORM_STRATEGY_REQUESTED:
        logger.info("Platform Strategy:\n- Selected: %s\n- Source: CLI\n- Earliest affected stage: %s",_PLATFORM_STRATEGY,EARLIEST_PLATFORM_DEPENDENT_STAGE)
    requested_mode = "force_all" if args.force_all else "force_stage" if args.force_stage else "from_stage" if args.from_stage else "stage" if args.stage else "resume" if args.resume else "default"
    cache.forced_stage = args.force_stage
    cache.reset_runtime_accounting(requested_mode=requested_mode,requested_stage=args.force_stage or args.stage or args.from_stage,stage_forced=bool(args.force_stage or args.force_all))
    if getattr(args,"default_continuation",False):
        for stage,outputs in _core_stage_outputs(project).items():
            if not outputs or any(not path.is_file() for path in outputs):
                cache.fail(stage,f"authoritative core artifact missing: {', '.join(str(path) for path in outputs)}")
                _finish_early_accounting(project.name,cache,started_at,preserve=False);return False
            expected=cache.expected(stage,[*project.pdf_files,*project.image_files,*project.auxiliary_files],module_version=f"core-default:{FUSION_VERSION}:namespace-v2")
            cache.begin(stage);cache.complete(stage,outputs,expected)
    if args.resume:
        first = cache.first_incomplete()
        selection = select_stages(from_stage=first) if first else StageSelection((), frozenset())
        cache.manifest["requested_mode"]="resume";cache.manifest["requested_stage"]=first;cache._save()
    knowledge = _artifact(KNOWLEDGE_OUTPUT_DIRECTORY, project.name, "")
    strategy = _artifact(STRATEGY_OUTPUT_DIRECTORY, project.name, "-strategy")
    inventory = _artifact(VISUAL_INVENTORY_OUTPUT_DIRECTORY, project.name, "-visual-inventory")
    source_manifest = SOURCE_IMAGES_OUTPUT_DIRECTORY / project.name / "manifest.json"
    if args.force_stage == "asset-intelligence" or args.stage == "asset-intelligence":
        if knowledge is None or not knowledge.exists() or not source_manifest.exists():
            logger.error("Missing prerequisites for forced Asset Intelligence: knowledge-fusion or visual-extraction")
            cache.block("asset-intelligence", "Missing prerequisites");_finish_early_accounting(project.name,cache,started_at,preserve=bool(args.force_stage));return False
        logger.info("[RUN] Asset Intelligence — forced; unchanged per-asset analyses remain reusable")
        cache.begin("asset-intelligence")
        result = AssetIntelligenceAgent().run(source_manifest, knowledge, retry_failed=True)
        if result is None:
            cache.fail("asset-intelligence", "Asset Intelligence failed");_finish_early_accounting(project.name,cache,started_at,preserve=bool(args.force_stage));return False
        intelligence, inventory = result
        expected_ai = cache.expected("asset-intelligence", [source_manifest, knowledge], module_version="1.0.0", prompt_version="1.0.0", model_policy=os.getenv("ASSET_INTELLIGENCE_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini")))
        cache.complete("asset-intelligence", [intelligence], expected_ai)
        if args.stage == "asset-intelligence" or args.force_stage == "asset-intelligence":
            _finish_early_accounting(project.name,cache,started_at,preserve=bool(args.force_stage));return True
    if args.force_stage == "deep-source-analysis" or args.stage == "deep-source-analysis":
        slug=_ranking_folder(project.name);knowledge_output=KNOWLEDGE_OUTPUT_DIRECTORY/slug/"project-knowledge.json";coverage_output=REPORTS_OUTPUT_DIRECTORY/f"source-coverage-{slug}.json";intelligence_path=_artifact(ASSET_INTELLIGENCE_OUTPUT_DIRECTORY,project.name,"-asset-intelligence")
        if not source_manifest.is_file() or not project.pdf_files:
            logger.error("Missing prerequisite for Deep Source Analysis: source PDF or visual extraction");cache.block("deep-source-analysis","Missing source PDF or visual-extraction manifest");_finish_early_accounting(project.name,cache,started_at,preserve=bool(args.force_stage));return False
        inputs=[*project.pdf_files,source_manifest]+([intelligence_path] if intelligence_path else []);expected=cache.expected("deep-source-analysis",inputs,module_version=DEEP_SOURCE_VERSION,schema_version=DEEP_SOURCE_SCHEMA_VERSION,model_policy="deterministic page-native PDF and visual linking; source PDF only; zero external calls")
        valid,reason=cache.valid("deep-source-analysis",[knowledge_output,coverage_output],expected)
        if valid and not args.force_stage:logger.info("[SKIP] Deep Source Analysis - %s",reason);cache.skip("deep-source-analysis",True)
        else:
            logger.info("[RUN] Deep Source Analysis — every PDF page; no internet, image generation, or Meta requests");cache.begin("deep-source-analysis");knowledge_output,coverage_output,payload=analyze_deep_source(PROJECT_ROOT,project.name,project.pdf_files);outputs=[knowledge_output,coverage_output,KNOWLEDGE_OUTPUT_DIRECTORY/slug/"project-knowledge-summary.md",REPORTS_OUTPUT_DIRECTORY/f"source-coverage-{slug}.md",REPORTS_OUTPUT_DIRECTORY/f"page-audit-{slug}.json",REPORTS_OUTPUT_DIRECTORY/f"page-audit-{slug}.md"];cache.complete("deep-source-analysis",outputs,expected,warnings=[f"knowledge status: {payload['knowledge_status']}"] if payload["knowledge_status"]!="complete" else None);logger.info("Deep Source Analysis completed: pages=%d status=%s score=%.1f API calls=0",json.loads(coverage_output.read_text(encoding="utf-8"))["pages_analyzed"],payload["knowledge_status"],payload["knowledge_completeness_score"])
        _finish_early_accounting(project.name,cache,started_at,preserve=bool(args.force_stage));return True
    if args.force_stage == "source-image-ranking" or args.stage == "source-image-ranking":
        if not source_manifest.exists():
            logger.error("Missing prerequisite for Source Image Ranking: visual-extraction")
            cache.block("source-image-ranking", "Missing visual-extraction manifest");_finish_early_accounting(project.name,cache,started_at,preserve=bool(args.force_stage));return False
        intelligence_path=_artifact(ASSET_INTELLIGENCE_OUTPUT_DIRECTORY,project.name,"-asset-intelligence");slug=_ranking_folder(project.name);deep_knowledge=KNOWLEDGE_OUTPUT_DIRECTORY/slug/"project-knowledge.json"
        inputs=[source_manifest]+([intelligence_path] if intelligence_path else [])+([deep_knowledge] if deep_knowledge.is_file() else [])
        output=SOURCE_IMAGE_RANKING_OUTPUT_DIRECTORY/f"source-image-ranking-{_ranking_folder(project.name)}.json"
        summary=SOURCE_IMAGE_RANKING_OUTPUT_DIRECTORY/f"source-image-selection-summary-{_ranking_folder(project.name)}.md"
        content_plan=SOURCE_IMAGE_RANKING_OUTPUT_DIRECTORY/f"visual-editorial-inventory-{_ranking_folder(project.name)}.md"
        content_plan_json=SOURCE_IMAGE_RANKING_OUTPUT_DIRECTORY/f"visual-editorial-inventory-{_ranking_folder(project.name)}.json"
        content_coverage=REPORTS_OUTPUT_DIRECTORY/f"content-coverage-{slug}.json";content_coverage_md=REPORTS_OUTPUT_DIRECTORY/f"content-coverage-{slug}.md"
        expected=cache.expected("source-image-ranking",inputs,module_version=RANKING_VERSION,schema_version=RANKING_SCHEMA_VERSION,model_policy="deterministic; persisted asset intelligence and deep-source knowledge only")
        valid,reason=cache.valid("source-image-ranking",[output,summary,content_plan,content_plan_json,content_coverage,content_coverage_md],expected)
        if valid and not args.force_stage:
            logger.info("[SKIP] Source Image Ranking - %s",reason);cache.skip("source-image-ranking",True)
        else:
            logger.info("[RUN] Source Image Ranking — deterministic; no AI or Meta requests")
            cache.begin("source-image-ranking")
            output,summary,payload=rank_source_images(SOURCE_IMAGES_OUTPUT_DIRECTORY,SOURCE_IMAGE_RANKING_OUTPUT_DIRECTORY,SELECTED_IMAGES_OUTPUT_DIRECTORY,project=project.name,max_selected=10,intelligence_path=intelligence_path,knowledge_path=deep_knowledge if deep_knowledge.is_file() else None)
            cache.complete("source-image-ranking",[output,summary,content_plan,content_plan_json,content_coverage,content_coverage_md],expected)
            logger.info("Source Image Ranking completed: discovered=%d selected=%d rejected=%d",payload["summary"]["images_discovered"],payload["summary"]["images_selected"],payload["summary"]["images_rejected"])
        _finish_early_accounting(project.name,cache,started_at,preserve=bool(args.force_stage));return True
    if args.force_stage == "project-brand-identity" or args.stage == "project-brand-identity":
        slug=_ranking_folder(project.name);manifest_path=SOURCE_IMAGE_RANKING_OUTPUT_DIRECTORY/f"project-brand-{slug}.json";knowledge_input=KNOWLEDGE_OUTPUT_DIRECTORY/f"{project.name}.json"
        if not source_manifest.is_file() or not knowledge_input.is_file():
            logger.error("Missing prerequisite for Project Brand Identity: visual extraction or knowledge");cache.block("project-brand-identity","Missing visual-extraction or knowledge artifact");_finish_early_accounting(project.name,cache,started_at,preserve=bool(args.force_stage));return False
        expected=cache.expected("project-brand-identity",[source_manifest,knowledge_input],module_version=PROJECT_BRAND_VERSION,schema_version=PROJECT_BRAND_SCHEMA_VERSION,model_policy="deterministic authentic catalogue extraction; no font guessing; zero API calls")
        valid,reason=cache.valid("project-brand-identity",[manifest_path],expected)
        if valid and not args.force_stage:logger.info("[SKIP] Project Brand Identity - %s",reason);cache.skip("project-brand-identity",True)
        else:
            logger.info("[RUN] Project Brand Identity — authentic catalogue assets; no AI or Meta requests");cache.begin("project-brand-identity");manifest_path,payload=extract_project_brand_identity(PROJECT_ROOT,project.name);outputs=[manifest_path,PROJECT_ROOT/"output/project-brand"/slug/"brand-identity.json"]+([PROJECT_ROOT/payload["project_wordmark"]["path"]] if payload["project_wordmark"]["available"] else []);cache.complete("project-brand-identity",outputs,expected);logger.info("Project Brand Identity completed: rendering=%s confidence=%.3f API calls=0",payload["preferred_project_name_rendering"],payload["project_wordmark"].get("confidence",0.0))
        _finish_early_accounting(project.name,cache,started_at,preserve=bool(args.force_stage));return True
    if args.force_stage == "branded-content" or args.stage == "branded-content":
        slug=_ranking_folder(project.name);ranking_path=SOURCE_IMAGE_RANKING_OUTPUT_DIRECTORY/f"source-image-ranking-{slug}.json";content_plan_input=CONTENT_OUTPUT_DIRECTORY/f"{project.name}-content-plan.json";canonical_input=CONTENT_INVENTORY_OUTPUT_DIRECTORY/f"{project.name}-content-opportunity-inventory.json";manifest_path=SOURCE_IMAGE_RANKING_OUTPUT_DIRECTORY/f"branded-content-{slug}.json";knowledge_input=KNOWLEDGE_OUTPUT_DIRECTORY/f"{project.name}.json";config_input=PROJECT_ROOT/"input"/"brand"/"brand-config.json";logo_inputs=sorted((PROJECT_ROOT/"input"/"brand"/"logos").glob("*"))
        try:ranking_current=json.loads(ranking_path.read_text(encoding="utf-8")).get("module_version")==RANKING_VERSION
        except (OSError,ValueError,TypeError):ranking_current=False
        if not ranking_current:
            logger.info("[RUN] Villa content-group refresh — current deep inventory and ranking logic; no AI or Meta requests")
            intelligence_path=_artifact(ASSET_INTELLIGENCE_OUTPUT_DIRECTORY,project.name,"-asset-intelligence");deep_knowledge=KNOWLEDGE_OUTPUT_DIRECTORY/slug/"project-knowledge.json"
            rank_source_images(SOURCE_IMAGES_OUTPUT_DIRECTORY,SOURCE_IMAGE_RANKING_OUTPUT_DIRECTORY,SELECTED_IMAGES_OUTPUT_DIRECTORY,project=project.name,max_selected=10,intelligence_path=intelligence_path,knowledge_path=deep_knowledge if deep_knowledge.is_file() else None)
        if not ranking_path.is_file():
            logger.error("Missing prerequisite for Branded Content: source-image-ranking")
            cache.block("branded-content","Missing source-image-ranking inventory");_finish_early_accounting(project.name,cache,started_at,preserve=bool(args.force_stage));return False
        if not content_plan_input.is_file() or not canonical_input.is_file():
            logger.error("Missing prerequisite for Branded Content: machine-readable content plan")
            cache.block("branded-content","Missing content-plan JSON");_finish_early_accounting(project.name,cache,started_at,preserve=bool(args.force_stage));return False
        project_brand_input=SOURCE_IMAGE_RANKING_OUTPUT_DIRECTORY/f"project-brand-{slug}.json";inputs=[ranking_path,content_plan_input,canonical_input,config_input,*logo_inputs]+([knowledge_input] if knowledge_input.is_file() else [])+([project_brand_input] if project_brand_input.is_file() else [])
        cached_outputs=[manifest_path]
        if manifest_path.is_file():
            try:cached_outputs += [PROJECT_ROOT/item["output_path"] for item in json.loads(manifest_path.read_text(encoding="utf-8")).get("items",[])]
            except (OSError,ValueError,KeyError):pass
        expected=cache.expected("branded-content",inputs,module_version=BRANDED_CONTENT_VERSION,schema_version=BRANDED_CONTENT_SCHEMA_VERSION,config={"mode":BRANDED_CONTENT_CACHE_MODE,"carousel_limit":10,"format":"instagram_feed_4_5"},model_policy="deterministic-local-content-plan-composition; zero API calls")
        valid,reason=cache.valid("branded-content",cached_outputs,expected)
        if valid and not args.force_stage:
            logger.info("[SKIP] Branded Content - %s",reason);cache.skip("branded-content",True)
        else:
            logger.info(BRANDED_CONTENT_RUN_DESCRIPTION);cache.begin("branded-content")
            manifest_path,payload=generate_branded_content(PROJECT_ROOT,project.name,limit=10);outputs=[manifest_path,*[PROJECT_ROOT/item["output_path"] for item in payload["items"]]];cache.complete("branded-content",outputs,expected);summary=payload["summary"];logger.info("Branded Content completed: planned_posts=%d renderable_posts=%d rendered_posts=%d deferred_posts=%d rendered_assets=%d API calls=0",summary["planned_posts"],summary["renderable_posts"],summary["rendered_posts"],summary["deferred_posts"],summary["rendered_assets"])
        _finish_early_accounting(project.name,cache,started_at,preserve=bool(args.force_stage));return True
    missing = [("knowledge-fusion", knowledge), ("visual-inventory", inventory), ("visual-extraction", source_manifest)]
    if any(path is None or not path.exists() for _, path in missing):
        absent = ", ".join(stage for stage,path in missing if path is None or not path.exists())
        logger.error("Missing or invalid prerequisite artifacts: %s. Run an earlier stage or python app.py first.", absent)
        target=args.force_stage or args.stage or args.from_stage or "visual-opportunities"
        cache.block(target,f"Missing prerequisites: {absent}");_finish_early_accounting(project.name,cache,started_at,preserve=bool(args.force_stage))
        return False
    assert knowledge and inventory
    platform_upstream=ancestors(EARLIEST_PLATFORM_DEPENDENT_STAGE) if _PLATFORM_STRATEGY_REQUESTED else set()
    paths: dict[str, Path] = {"knowledge": knowledge, "strategy": strategy, "inventory": inventory}
    existing_reci=_artifact(CREATIVE_INTELLIGENCE_OUTPUT_DIRECTORY,project.name,"-creative-opportunity-map")
    if existing_reci:paths["creative_intelligence"]=existing_reci
    if args.force_stage:
        valid_prerequisites, prerequisite_error = _validate_forced_prerequisites(args.force_stage, project.name, cache)
        if not valid_prerequisites:
            cache.block(args.force_stage, prerequisite_error or "Invalid prerequisite")
            logger.error("Cannot force stage '%s': %s", args.force_stage, prerequisite_error)
            cache.finish()
            _log_project_accounting(project.name,cache,started_at)
            return False
    run_count = skip_count = 0
    try:
        start_index = min((STAGE_ORDER.index(s) for s in selection.requested), default=len(STAGE_ORDER))
        for stage in STAGE_ORDER:
            if stage not in selection.requested:
                if stage in platform_upstream:
                    reuse_path=knowledge if stage in {"knowledge-extraction","knowledge-fusion","knowledge-evaluation"} else inventory if stage in {"asset-intelligence","visual-inventory"} else source_manifest if stage=="visual-extraction" else (project.pdf_files[0] if project.pdf_files else project.image_files[0])
                    cache.reuse_prerequisite(stage,reuse_path);logger.info("[SKIP] %s - valid upstream artifact",stage)
                elif stage not in cache.runtime_records: cache.not_requested(stage,preserve_persistent_status=bool(args.force_stage))
                continue
            if stage == "deep-source-analysis":
                slug=_ranking_folder(project.name);deep_knowledge=KNOWLEDGE_OUTPUT_DIRECTORY/slug/"project-knowledge.json";coverage=REPORTS_OUTPUT_DIRECTORY/f"source-coverage-{slug}.json"
                inputs=[*project.pdf_files,source_manifest];expected=cache.expected(stage,inputs,module_version=DEEP_SOURCE_VERSION,schema_version=DEEP_SOURCE_SCHEMA_VERSION,model_policy="deterministic page-native PDF and visual linking; source PDF only; zero external calls")
                valid,reason=cache.valid(stage,[deep_knowledge,coverage],expected)
                if valid and stage not in selection.forced:cache.skip(stage,True);skip_count+=1
                else:
                    cache.begin(stage);deep_knowledge,coverage,payload=analyze_deep_source(PROJECT_ROOT,project.name,project.pdf_files);cache.complete(stage,[deep_knowledge,coverage],expected,warnings=[f"knowledge status: {payload['knowledge_status']}"] if payload["knowledge_status"]!="complete" else None);run_count+=1
            elif stage == "source-image-ranking":
                slug=_ranking_folder(project.name);deep_knowledge=KNOWLEDGE_OUTPUT_DIRECTORY/slug/"project-knowledge.json";intelligence=_artifact(ASSET_INTELLIGENCE_OUTPUT_DIRECTORY,project.name,"-asset-intelligence");output=SOURCE_IMAGE_RANKING_OUTPUT_DIRECTORY/f"source-image-ranking-{slug}.json";summary=SOURCE_IMAGE_RANKING_OUTPUT_DIRECTORY/f"source-image-selection-summary-{slug}.md";editorial=SOURCE_IMAGE_RANKING_OUTPUT_DIRECTORY/f"visual-editorial-inventory-{slug}.json"
                inputs=[source_manifest,*([intelligence] if intelligence else []),*([deep_knowledge] if deep_knowledge.is_file() else [])];expected=cache.expected(stage,inputs,module_version=RANKING_VERSION,schema_version=RANKING_SCHEMA_VERSION,model_policy="deterministic; persisted asset intelligence and deep-source knowledge only")
                valid,reason=cache.valid(stage,[output,summary,editorial],expected)
                if valid and stage not in selection.forced:cache.skip(stage,True);skip_count+=1
                else:
                    cache.begin(stage);output,summary,_=rank_source_images(SOURCE_IMAGES_OUTPUT_DIRECTORY,SOURCE_IMAGE_RANKING_OUTPUT_DIRECTORY,SELECTED_IMAGES_OUTPUT_DIRECTORY,project=project.name,max_selected=10,intelligence_path=intelligence,knowledge_path=deep_knowledge if deep_knowledge.is_file() else None);cache.complete(stage,[output,summary,editorial],expected);run_count+=1
            elif stage == "project-brand-identity":
                slug=_ranking_folder(project.name);output=SOURCE_IMAGE_RANKING_OUTPUT_DIRECTORY/f"project-brand-{slug}.json";expected=cache.expected(stage,[source_manifest,knowledge],module_version=PROJECT_BRAND_VERSION,schema_version=PROJECT_BRAND_SCHEMA_VERSION,model_policy="deterministic authentic catalogue extraction; no font guessing; zero API calls")
                valid,reason=cache.valid(stage,[output],expected)
                if valid and stage not in selection.forced:cache.skip(stage,True);skip_count+=1
                else:cache.begin(stage);output,_=extract_project_brand_identity(PROJECT_ROOT,project.name);cache.complete(stage,[output],expected);run_count+=1
            elif stage == "visual-inventory":
                intelligence=_artifact(ASSET_INTELLIGENCE_OUTPUT_DIRECTORY,project.name,"-asset-intelligence");expected=cache.expected(stage,[source_manifest,knowledge],module_version="1.0.0",model_policy=os.getenv("ASSET_INTELLIGENCE_MODEL",os.getenv("OPENAI_MODEL","gpt-4o-mini")))
                valid,reason=cache.valid(stage,[inventory],expected)
                if valid and stage not in selection.forced:cache.skip(stage,True);skip_count+=1
                else:
                    if not intelligence:raise ValueError("asset-intelligence prerequisite is missing")
                    cache.begin(stage);cache.complete(stage,[inventory],expected);run_count+=1
            elif stage == "creative-intelligence":
                evaluation=REPORTS_OUTPUT_DIRECTORY/f"{project.name}-evaluation.json";plan_path=PROJECT_ROOT/"output"/"plan-intelligence"/f"{project.name}-plan-intelligence.json"
                creative_library=PROJECT_ROOT/"data"/"creative-intelligence"/"library.json"
                output=CREATIVE_INTELLIGENCE_OUTPUT_DIRECTORY/f"{project.name}-creative-opportunity-map.json"
                inputs=[knowledge,inventory,creative_library,*([evaluation] if evaluation.is_file() else []),*([plan_path] if plan_path.is_file() else [])]
                expected=cache.expected(stage,inputs,module_version="1.0.0",schema_version="1.0.0",model_policy="deterministic verified intelligence only; zero external calls",semantic_json_inputs=True)
                valid,reason=cache.valid(stage,[output],expected)
                if valid and stage not in selection.forced:cache.skip(stage,True);skip_count+=1
                else:
                    cache.begin(stage);output=RealEstateCreativeIntelligence().run(knowledge,evaluation if evaluation.is_file() else None,inventory,plan_path if plan_path.is_file() else None);cache.complete(stage,[output],expected);run_count+=1
                paths["creative_intelligence"]=output
            elif stage == "campaign-intelligence":
                reci=paths.get("creative_intelligence") or _artifact(CREATIVE_INTELLIGENCE_OUTPUT_DIRECTORY,project.name,"-creative-opportunity-map")
                if not reci:raise ValueError("creative-intelligence prerequisite is missing")
                library=PROJECT_ROOT/"data"/"creative-intelligence"/"library.json";performance=PROJECT_ROOT/"data"/"performance-learning"/"creative-learning-profile.json"
                plan_path=PROJECT_ROOT/"output"/"plan-intelligence"/f"{project.name}-plan-intelligence.json"
                output=PROJECT_ROOT/"output"/"campaign-intelligence"/f"{project.name}-campaign-decisions.json";state_output=PROJECT_ROOT/"output"/"campaign-intelligence"/f"{project.name}-campaign-state.json"
                inputs=[knowledge,reci,library,inventory,*([performance] if performance.is_file() else []),*([plan_path] if plan_path.is_file() else [])]
                expected=cache.expected(stage,inputs,module_version="1.0.0",schema_version="1.0.0",model_policy="deterministic campaign authority; simulation only; zero publishing calls",semantic_json_inputs=True)
                valid,reason=cache.valid(stage,[output,state_output],expected)
                if valid and stage not in selection.forced:cache.skip(stage,True);skip_count+=1
                else:
                    history=[]
                    try:
                        ledger=PublicationLedger(PROJECT_ROOT);ledger._validate();history=ledger.records()
                    except Exception:history=[]
                    cache.begin(stage);state_output,output=CampaignIntelligenceEngine(PROJECT_ROOT).run(project_id=project.name,knowledge_path=knowledge,reci_path=reci,library_path=library,performance_path=performance if performance.is_file() else None,inventory_path=inventory,plan_path=plan_path if plan_path.is_file() else None,publication_history=history,simulation=True);cache.complete(stage,[state_output,output],expected);run_count+=1
                paths["campaign_intelligence"]=output
            elif stage == "marketing-strategy":
                reci=paths.get("creative_intelligence") or _artifact(CREATIVE_INTELLIGENCE_OUTPUT_DIRECTORY,project.name,"-creative-opportunity-map")
                if not reci:raise ValueError("creative-intelligence prerequisite is missing")
                campaign_intelligence=paths.get("campaign_intelligence") or _artifact(PROJECT_ROOT/"output"/"campaign-intelligence",project.name,"-campaign-decisions")
                if not campaign_intelligence:raise ValueError("campaign-intelligence prerequisite is missing")
                output=_artifact(STRATEGY_OUTPUT_DIRECTORY,project.name,"-strategy");expected=cache.expected(stage,[knowledge,inventory,reci,campaign_intelligence],module_version="1.3.0",model_policy=os.getenv("OPENAI_MODEL","gpt-4o-mini"))
                valid,reason=cache.valid(stage,[output] if output else [],expected)
                if valid and stage not in selection.forced:cache.skip(stage,True);skip_count+=1
                else:
                    cache.begin(stage);output=run_legacy_strategy_advisory(MarketingStrategyAgent().run, knowledge,reci,campaign_intelligence)
                    if output is None:raise RuntimeError("Marketing Strategy failed")
                    cache.complete(stage,[output],expected);run_count+=1
                strategy=output
                paths["strategy"]=output
            elif stage == "visual-opportunities":
                if strategy is None:raise ValueError("marketing-strategy prerequisite is missing")
                output = VISUAL_OPPORTUNITIES_OUTPUT_DIRECTORY / f"{project.name}-visual-opportunities.json"
                canonical = CONTENT_INVENTORY_OUTPUT_DIRECTORY / f"{project.name}-content-opportunity-inventory.json"
                expected = cache.expected(stage, [knowledge, strategy, inventory], module_version=PLANNING_ENGINE_VERSION)
                valid, reason = cache.valid(stage, [output,canonical], expected)
                if valid:
                    try:
                        loaded=load_content_opportunity_inventory(canonical)
                        if loaded.project_id!=project.name or loaded.inventory_version!=INVENTORY_VERSION:raise ValueError("wrong project or version")
                        compatibility=json.loads(output.read_text(encoding="utf-8"))
                        if compatibility.get("canonical_inventory_sha256")!=sha256_file(canonical):raise ValueError("canonical hash mismatch")
                    except (OSError,ValueError,KeyError,TypeError) as error:
                        valid,reason=False,f"invalid canonical inventory: {error}"
                if valid and stage not in selection.forced: logger.info("[SKIP] Visual Opportunity Engine - %s", reason); cache.skip(stage, True); skip_count += 1
                else:
                    logger.info("[RUN] Visual Opportunity Engine"); cache.begin(stage)
                    output = run_legacy_visual_opportunity_compat(VisualOpportunityEngine().run, knowledge, inventory, strategy)
                    compatibility = json.loads(output.read_text(encoding="utf-8"))
                    canonical = Path(str(compatibility.get("canonical_inventory_path", "")))
                    cache.complete(stage, [output, *([canonical] if canonical.is_file() else [])], expected); run_count += 1
                paths["opportunities"] = output
            elif stage in {"campaign-planner", "content-planner"}:
                if "opportunities" not in paths:
                    paths["opportunities"] = _artifact(VISUAL_OPPORTUNITIES_OUTPUT_DIRECTORY, project.name, "-visual-opportunities")  # type: ignore[assignment]
                if paths.get("opportunities") is None: raise ValueError("visual-opportunities prerequisite is missing")
                if stage == "content-planner" and "campaign_plan" not in paths:
                    campaign_input = _artifact(CAMPAIGNS_OUTPUT_DIRECTORY, project.name, "-campaign-plan")
                    if campaign_input is None:
                        raise ValueError("campaign-planner prerequisite is missing")
                    paths["campaign_plan"] = campaign_input
                reci=paths.get("creative_intelligence") or _artifact(CREATIVE_INTELLIGENCE_OUTPUT_DIRECTORY,project.name,"-creative-opportunity-map")
                if not reci:raise ValueError("creative-intelligence prerequisite is missing")
                campaign_intelligence=paths.get("campaign_intelligence") or _artifact(PROJECT_ROOT/"output"/"campaign-intelligence",project.name,"-campaign-decisions")
                if not campaign_intelligence:raise ValueError("campaign-intelligence prerequisite is missing")
                expected = cache.expected(stage, [knowledge, strategy, inventory, paths["opportunities"],reci,campaign_intelligence], module_version=f"{PLANNING_ENGINE_VERSION}:{PLANNING_CUTOVER_VERSION}:{REVIEWER_VERSION if stage=='content-planner' else 'campaign'}", config={"platform_strategy": _PLATFORM_STRATEGY,"creative_reviewer_version":REVIEWER_VERSION} if stage=="content-planner" else {"platform_strategy":_PLATFORM_STRATEGY})
                suffix = "-campaign-plan" if stage == "campaign-planner" else "-content-plan"
                directory = CAMPAIGNS_OUTPUT_DIRECTORY if stage == "campaign-planner" else CONTENT_OUTPUT_DIRECTORY
                output = _artifact(directory, project.name, suffix)
                valid, reason = cache.valid(stage, [output] if output else [], expected)
                if valid and stage not in selection.forced: logger.info("[SKIP] %s - %s", "Campaign Planner" if stage=="campaign-planner" else "Smart Content Planner", reason); cache.skip(stage, True); skip_count += 1
                elif stage == "content-planner" and paths.get("content_plan") and paths["content_plan"].exists() and "campaign_plan" in paths:
                    logger.info("[RUN] Smart Content Planner — completed in shared deterministic planning pass")
                    output = paths["content_plan"]; cache.complete(stage, [output], expected); run_count += 1
                else:
                    logger.info("[RUN] %s", "Campaign Planner" if stage=="campaign-planner" else "Smart Content Planner"); cache.begin(stage)
                    products = cutover_legacy_planning_products(
                        project_id=project.name,
                        planning_engine=PlanningEngine(),
                        planning_args=(knowledge, strategy, inventory, paths["opportunities"]),
                        planning_kwargs={
                            "creative_intelligence_path": reci,
                            "campaign_intelligence_path": campaign_intelligence,
                            "write_campaign": stage == "campaign-planner",
                            "platform_strategy": _PLATFORM_STRATEGY,
                        },
                    )
                    paths.update(products); output = products["campaign_plan" if stage=="campaign-planner" else "content_plan"]
                    cache.complete(stage, [output], expected); run_count += 1
                if stage=="content-planner":
                    output,review=RealEstateCreativeReviewer(PROJECT_ROOT).review(project.name,output,knowledge,strategy,inventory);logger.info("Real Estate Creative Reviewer completed: %s",review)
                paths["campaign_plan" if stage=="campaign-planner" else "content_plan"] = output  # type: ignore[assignment]
            elif stage == "branded-content":
                canonical=CONTENT_INVENTORY_OUTPUT_DIRECTORY/f"{project.name}-content-opportunity-inventory.json"
                if not canonical.is_file() or not paths.get("content_plan"):raise ValueError("Branded Content requires canonical Department 3 strategy")
                output=SOURCE_IMAGE_RANKING_OUTPUT_DIRECTORY/f"branded-content-{_ranking_folder(project.name)}.json"
                expected=cache.expected(stage,[canonical,paths["content_plan"]],module_version=BRANDED_CONTENT_VERSION,schema_version=BRANDED_CONTENT_SCHEMA_VERSION)
                valid,reason=cache.valid(stage,[output],expected)
                if valid and stage not in selection.forced:cache.skip(stage,True);skip_count+=1
                else:
                    cache.begin(stage);output,_=generate_branded_content(PROJECT_ROOT,project.name);cache.complete(stage,[output],expected);run_count+=1
            else:
                # Downstream execution keeps the existing agent boundaries and source-only validators.
                if not _run_downstream_stage(stage, project.name, paths, knowledge, strategy, inventory, source_manifest, cache, selection): return False
                run_count += 1
        if _PLATFORM_STRATEGY_REQUESTED:
            reused=sum(x.get("execution_state")=="skipped_valid_prerequisite" for x in cache.runtime_records.values());cache.manifest["platform_strategy_upstream_artifacts_reused"]=reused;logger.info("Platform Strategy upstream artifacts reused: %d",reused)
        cache.finish();_log_project_accounting(project.name,cache,started_at)
        return True
    except PlanningNoContentError as error:
        blocked = next((s for s,v in cache.manifest["stage_statuses"].items() if v=="running"), "campaign-planner")
        cache.block(blocked, str(error));cache.finish();_log_project_accounting(project.name,cache,started_at)
        logger.error("Blocked stage: %s\nReason: %s", blocked, error)
        return False
    except Exception as error:
        failed = next((s for s,v in cache.manifest["stage_statuses"].items() if v=="running"), args.stage or args.from_stage or "visual-opportunities")
        artifact=paths.get(failed.replace("-planner","_plan")) or strategy_artifact
        cache.fail(failed, error);cache.manifest["failure"]["artifact"]=str(artifact);cache._save();cache.finish();_log_project_accounting(project.name,cache,started_at);logger.error("Failed stage: %s\nReason: %s\nArtifact involved: %s", failed, error, artifact); return False


def _persist_platform_strategy(project:str,strategy:str,source:str)->Path:
    directory=PROJECT_ROOT/"output"/"platform-strategy";path=directory/f"{project}-platform-strategy.json"
    previous={}
    try:previous=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError):pass
    selected_at=previous.get("selected_at") if previous.get("platform_strategy")==strategy and previous.get("source")==source else datetime.now(timezone.utc).isoformat()
    value={"project_id":project,"platform_strategy":strategy,"strategy_version":"1.0.0","selected_at":selected_at,"source":source}
    if previous!=value:
        directory.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return path


def _core_stage_outputs(project:ProjectInput)->dict[str,list[Path]]:
    """Authoritative evidence emitted by the monolithic Department 1/2 core."""
    documents=KNOWLEDGE_OUTPUT_DIRECTORY/project.name/"documents"
    markdown=MARKDOWN_OUTPUT_DIRECTORY/project.name
    return {
        "discover":[*project.pdf_files,*project.image_files,*project.auxiliary_files],
        "document-analysis":[PROJECT_ROOT/"output"/"inventory"/f"{project.name}-document-analysis.json"],
        "text-extraction":sorted(markdown.glob("*.md")),
        "knowledge-extraction":sorted(path for path in documents.glob("*.json") if not path.name.endswith("-classification.json")),
        "knowledge-fusion":[KNOWLEDGE_OUTPUT_DIRECTORY/f"{project.name}.json"],
        "knowledge-evaluation":[REPORTS_OUTPUT_DIRECTORY/f"{project.name}-evaluation.json"],
        "visual-extraction":[PROJECT_ROOT/"output"/"source-images"/project.name/"manifest.json"],
        "asset-intelligence":[PROJECT_ROOT/"output"/"asset-intelligence"/f"{project.name}-asset-intelligence.json",PROJECT_ROOT/"output"/"visual-inventory"/f"{project.name}-visual-inventory.json"],
    }


def _log_project_accounting(project: str, cache: StageCache, started_at: float) -> None:
    summary=cache.accounting_summary();summary["project_id"]=project;summary["total_wall_clock_ms"]=round((time.monotonic()-started_at)*1000)
    cache.manifest["project_summary"]=summary;cache._save();_RUN_ACCOUNTING.append(summary)
    console_project=project.encode("ascii","backslashreplace").decode("ascii")
    logger.info("Project Execution Summary:\n- Project: %s\n- Stages run: %d\n- Stages skipped from cache: %d\n- Valid prerequisites reused: %d\n- Stages not requested: %d\n- Failed stages: %d\n- Blocked stages: %d\n- API calls executed: %d\n- API calls avoided by cache: %d\n- API calls failed: %d\n- API calls retried: %d\n- Executed-stage duration: %dms\n- Cached-stage lookup duration: %dms\n- Total wall-clock duration: %dms",
                console_project,summary["stages_executed"],summary["stages_skipped_cached"],summary["prerequisites_reused"],summary["stages_not_requested"],summary["stages_failed"],summary["stages_blocked"],summary["api_calls_executed"],summary["api_calls_avoided_by_cache"],summary["api_calls_failed"],summary["api_calls_retried"],summary["executed_stage_duration_ms"],summary["cached_stage_lookup_duration_ms"],summary["total_wall_clock_ms"])


def _finish_early_accounting(project: str, cache: StageCache, started_at: float, *, preserve: bool) -> None:
    for name in STAGE_ORDER:
        if name not in cache.runtime_records:cache.not_requested(name,preserve_persistent_status=preserve)
    cache.finish();_log_project_accounting(project,cache,started_at)


def _run_downstream_stage(stage: str, project: str, paths: dict[str, Path], knowledge: Path, strategy: Path, inventory: Path, source_manifest: Path, cache: StageCache, selection: StageSelection) -> bool:
    if stage in {"visual-art-director","brand-composer"}:
        kit, identity_result, readiness_result = ensure_brand_analysis(PROJECT_ROOT)
        logger.info(
            "Shared Brand Foundation: inventory=%s identity=%s readiness=%s kit_cached=%s identity_cached=%s",
            kit.inventory_path, identity_result.path, readiness_result.path,
            kit.cached, identity_result.cached,
        )
    # Resolve cached prerequisites produced in an earlier run.
    if "content_plan" not in paths:
        reviewed_plan=PROJECT_ROOT/"output"/"creative-reviews"/"approved"/f"{project}-content-plan.json"
        paths["content_plan"] = reviewed_plan if reviewed_plan.is_file() else _artifact(CONTENT_OUTPUT_DIRECTORY, project, "-content-plan")  # type: ignore[assignment]
    if paths.get("content_plan") is None: raise ValueError("content-planner prerequisite is missing")
    release_manifests=sorted((PROJECT_ROOT/"output"/"releases"/project).glob("release-*/manifest.json"))
    existing_by_stage = {
        "creative-director": _artifact(CREATIVE_DIRECTIONS_OUTPUT_DIRECTORY, project, "-creative-directions"),
        "scene-planner": _artifact(SCENE_PLANS_OUTPUT_DIRECTORY, project, "-scene-plans"),
        "shot-planner": _artifact(SHOT_PLANS_OUTPUT_DIRECTORY, project, "-shot-plans"),
        "image-processing-planner": _artifact(IMAGE_PROCESSING_PLANS_OUTPUT_DIRECTORY, project, "-image-processing-plans"),
        "image-prompt-generator": _artifact(IMAGE_PROMPTS_OUTPUT_DIRECTORY, project, "-image-prompts"),
        "detail-preservation-enhancer": DETAIL_ENHANCED_OUTPUT_DIRECTORY / project / "detail-enhancement-manifest.json",
        "deterministic-image-processor": _artifact(PRODUCTION_MANIFESTS_OUTPUT_DIRECTORY, project, "-production-manifest"),
        "image-output-qa": IMAGE_QA_OUTPUT_DIRECTORY/f"{project}-image-qa.json",
        "visual-art-director": VISUAL_DIRECTIONS_OUTPUT_DIRECTORY/f"{project}-visual-direction-contracts.json",
        "brand-composer": PROJECT_ROOT / "output" / "brand-composition-plans" / f"{project}-brand-composition-plans.json",
        "branded-image-qa": IMAGE_QA_OUTPUT_DIRECTORY / f"{project}-branded-image-qa.json",
        "creative-visual-qa": IMAGE_QA_OUTPUT_DIRECTORY / f"{project}-creative-visual-qa.json",
        "self-correction": PROJECT_ROOT/"output"/"corrections"/f"{project}-self-correction-log.json",
        "provenance-audit": PROJECT_ROOT/"output"/"provenance"/f"{project}-provenance-audit.json",
        "production-quality-report": PROJECT_ROOT/"output"/"reports"/f"{project}-production-quality-report.json",
        "release-manager": release_manifests[-1] if release_manifests else None,
        "content-grouping-analyzer": PROJECT_ROOT/"output"/"content-groups"/f"{project}-content-groups.json",
        "caption-generator": PROJECT_ROOT/"output"/"captions"/f"{project}-captions.json",
        "hashtag-generator": PROJECT_ROOT/"output"/"hashtags"/f"{project}-hashtags.json",
        "alt-text-generator": PROJECT_ROOT/"output"/"alt-text"/f"{project}-alt-text.json",
        "post-package-builder": PROJECT_ROOT/"output"/"post-packages"/f"{project}-post-packages.json",
        "post-package-qa": IMAGE_QA_OUTPUT_DIRECTORY/f"{project}-post-package-qa.json",
        "social-content-review": PROJECT_ROOT/"output"/"social-review"/f"{project}-social-review.html",
        "publishing-queue": PROJECT_ROOT/"output"/"publishing"/f"{project}-publishing-queue.json",
        "scheduling-engine": PROJECT_ROOT/"output"/"publishing"/f"{project}-schedule.json",
        "publish-preflight": PROJECT_ROOT/"output"/"publishing"/f"{project}-preflight.json",
        "mock-platform-adapter": PROJECT_ROOT/"output"/"publishing"/f"{project}-publication-manifest.json",
        "publication-manifest": PROJECT_ROOT/"output"/"publishing"/f"{project}-publication-manifest.json",
        "meta-platform-adapter": None,
        "publishing-queue": PROJECT_ROOT/"output"/"publishing"/f"{project}-publishing-queue.json",
        "scheduling-engine": PROJECT_ROOT/"output"/"publishing"/f"{project}-schedule.json",
        "publish-preflight": PROJECT_ROOT/"output"/"publishing"/f"{project}-preflight.json",
        "mock-platform-adapter": None,
        "publication-manifest": PROJECT_ROOT/"output"/"publishing"/f"{project}-publication-manifest.json",
        "production-manifest": _artifact(PRODUCTION_MANIFESTS_OUTPUT_DIRECTORY, project, "-production-manifest"),
        "review-gallery": REVIEW_OUTPUT_DIRECTORY / f"{project}-review-gallery.html",
    }
    existing = existing_by_stage.get(stage)
    input_paths = [knowledge, strategy, inventory, paths["content_plan"]]
    upstream_dependencies={
        "scene-planner":[existing_by_stage["creative-director"],PROJECT_ROOT/"input/visual-review/project-overview-reviews.json",PROJECT_ROOT/"input/visual-review/project-layout-reviews.json"],
        "shot-planner":[existing_by_stage["creative-director"],existing_by_stage["scene-planner"]],
        "image-processing-planner":[existing_by_stage["shot-planner"],source_manifest],
    }
    input_paths += [path for path in upstream_dependencies.get(stage,[]) if path is not None]
    if stage == "image-prompt-generator":
        processing = _artifact(IMAGE_PROCESSING_PLANS_OUTPUT_DIRECTORY, project, "-image-processing-plans")
        intelligence = _artifact(ASSET_INTELLIGENCE_OUTPUT_DIRECTORY, project, "-asset-intelligence")
        shots = _artifact(SHOT_PLANS_OUTPUT_DIRECTORY, project, "-shot-plans")
        if not processing or not intelligence or not shots: raise ValueError("image prompt generator prerequisites are missing")
        input_paths = [processing, shots, paths["content_plan"], inventory, intelligence]
    elif stage in {"detail-preservation-enhancer","deterministic-image-processor","image-output-qa","visual-art-director","brand-composer","branded-image-qa","creative-visual-qa","self-correction","provenance-audit","production-quality-report","release-manager","content-grouping-analyzer","caption-generator","hashtag-generator","alt-text-generator","post-package-builder","post-package-qa","social-content-review","publishing-queue","scheduling-engine","publish-preflight","mock-platform-adapter","meta-platform-adapter","publication-manifest","production-manifest","review-gallery"}:
        prompt_file=_artifact(IMAGE_PROMPTS_OUTPUT_DIRECTORY,project,"-image-prompts")
        production_manifest=_artifact(PRODUCTION_MANIFESTS_OUTPUT_DIRECTORY,project,"-production-manifest")
        if stage in {"detail-preservation-enhancer","deterministic-image-processor"}:
            processing=_artifact(IMAGE_PROCESSING_PLANS_OUTPUT_DIRECTORY,project,"-image-processing-plans");intelligence=_artifact(ASSET_INTELLIGENCE_OUTPUT_DIRECTORY,project,"-asset-intelligence")
            if not prompt_file or not processing or not intelligence:raise ValueError("deterministic production prerequisites are missing")
            input_paths=[prompt_file,processing,inventory,intelligence]
            if stage=="deterministic-image-processor":
                detail_input=DETAIL_ENHANCED_OUTPUT_DIRECTORY/project/"detail-enhancement-manifest.json"
                if detail_input.is_file():input_paths.append(detail_input)
        elif stage == "visual-art-director":
            if not prompt_file:raise ValueError("visual art director source-planning prerequisite is missing")
            input_paths=[prompt_file,knowledge,paths["content_plan"],inventory,
                PROJECT_ROOT/"input"/"brand"/"brand-config.json",PROJECT_ROOT/"output"/"brand-analysis"/"domus-erbil-logo-inventory.json"]
            from src.creative.editorial_profile import profile_path
            input_paths.append(profile_path(PROJECT_ROOT,project))
            input_paths += sorted((PROJECT_ROOT/"input"/"brand"/"logos").glob("*"))
            history=PROJECT_ROOT/"output"/"visual-history"/f"{project}-visual-direction-history.json"
            if history.is_file():input_paths.append(history)
            try:input_paths += [Path((item.get("source_asset_paths") or [""])[0]) for item in json.loads(prompt_file.read_text(encoding="utf-8")).get("prompts",[]) if item.get("source_asset_paths")]
            except (OSError,ValueError):pass
        elif stage == "brand-composer":
            input_paths=[VISUAL_DIRECTIONS_OUTPUT_DIRECTORY/f"{project}-visual-direction-contracts.json",
                PROJECT_ROOT/"input"/"brand"/"brand-config.json",PROJECT_ROOT/"output"/"brand-analysis"/"domus-erbil-logo-inventory.json",
                PROJECT_ROOT/"output"/"brand-analysis"/"domus-erbil-brand-identity.json",PROJECT_ROOT/"output"/"brand-analysis"/"domus-erbil-brand-readiness.json"]
            from src.creative.editorial_profile import profile_path
            input_paths.append(profile_path(PROJECT_ROOT,project))
            input_paths += sorted((PROJECT_ROOT/"input"/"brand"/"logos").glob("*"))
        elif stage == "image-output-qa":
            input_paths=[PROJECT_ROOT/"output"/"brand-composition-plans"/f"{project}-brand-composition-plans.json",VISUAL_DIRECTIONS_OUTPUT_DIRECTORY/f"{project}-visual-direction-contracts.json"]
            try:input_paths += [Path(item["branded_image_path"]) for item in json.loads(input_paths[0].read_text(encoding="utf-8")).get("plans",[]) if item.get("branded_image_path")]
            except (OSError,ValueError):pass
        elif not production_manifest and stage in {"production-manifest","review-gallery"}:raise ValueError("production manifest prerequisite is missing")
        elif stage == "branded-image-qa":
            input_paths=[PROJECT_ROOT/"output"/"brand-composition-plans"/f"{project}-brand-composition-plans.json"]
            try:
                plan_payload=json.loads(input_paths[0].read_text(encoding="utf-8"))
                input_paths += [Path(item["branded_image_path"]) for item in plan_payload.get("plans",[]) if item.get("branded_image_path")]
            except (OSError, ValueError): pass
        elif stage in {"creative-visual-qa","self-correction","provenance-audit","production-quality-report","release-manager"}:
            hardening_inputs={
                "creative-visual-qa":[IMAGE_QA_OUTPUT_DIRECTORY/f"{project}-branded-image-qa.json",PROJECT_ROOT/"output"/"production-manifests"/f"{project}-branded-production-manifest.json",PROJECT_ROOT/"output"/"brand-composition-plans"/f"{project}-brand-composition-plans.json",VISUAL_DIRECTIONS_OUTPUT_DIRECTORY/f"{project}-visual-direction-contracts.json"],
                "self-correction":[IMAGE_QA_OUTPUT_DIRECTORY/f"{project}-creative-visual-qa.json"],
                "provenance-audit":[PROJECT_ROOT/"output"/"corrections"/f"{project}-self-correction-log.json",PROJECT_ROOT/"output"/"production-manifests"/f"{project}-branded-production-manifest.json"],
                "production-quality-report":[PROJECT_ROOT/"output"/"provenance"/f"{project}-provenance-audit.json",IMAGE_QA_OUTPUT_DIRECTORY/f"{project}-creative-visual-qa.json"],
                "release-manager":[PROJECT_ROOT/"output"/"reports"/f"{project}-production-quality-report.json",PROJECT_ROOT/"output"/"provenance"/f"{project}-provenance-audit.json",PROJECT_ROOT/"output"/"production-manifests"/f"{project}-branded-production-manifest.json",IMAGE_QA_OUTPUT_DIRECTORY/f"{project}-branded-image-qa.json",IMAGE_QA_OUTPUT_DIRECTORY/f"{project}-creative-visual-qa.json"]}
            input_paths=hardening_inputs[stage]
        elif stage in {"content-grouping-analyzer","caption-generator","hashtag-generator","alt-text-generator","post-package-builder","post-package-qa","social-content-review"}:
            package_inputs={"content-grouping-analyzer":[release_manifests[-1] if release_manifests else PROJECT_ROOT/"output"/"releases"/project/"missing.json",PROJECT_ROOT/"output"/"production-manifests"/f"{project}-branded-production-manifest.json",PROJECT_ROOT/"output"/"campaigns"/f"{project}-campaign-plan.json",PROJECT_ROOT/"output"/"content"/f"{project}-content-plan.json"],"caption-generator":[PROJECT_ROOT/"output"/"content-groups"/f"{project}-content-groups.json",PROJECT_ROOT/"output"/"knowledge"/f"{project}.json",PROJECT_ROOT/"output"/"asset-intelligence"/f"{project}-asset-intelligence.json",PROJECT_ROOT/"output"/"provenance"/f"{project}-provenance-audit.json"],"hashtag-generator":[PROJECT_ROOT/"output"/"captions"/f"{project}-captions.json",PROJECT_ROOT/"output"/"knowledge"/f"{project}.json"],"alt-text-generator":[PROJECT_ROOT/"output"/"content-groups"/f"{project}-content-groups.json",inventory],"post-package-builder":[PROJECT_ROOT/"output"/"content-groups"/f"{project}-content-groups.json",PROJECT_ROOT/"output"/"captions"/f"{project}-captions.json",PROJECT_ROOT/"output"/"hashtags"/f"{project}-hashtags.json",PROJECT_ROOT/"output"/"alt-text"/f"{project}-alt-text.json",PROJECT_ROOT/"output"/"provenance"/f"{project}-provenance-audit.json"],"post-package-qa":[PROJECT_ROOT/"output"/"post-packages"/f"{project}-post-packages.json",PROJECT_ROOT/"output"/"provenance"/f"{project}-provenance-audit.json"],"social-content-review":[PROJECT_ROOT/"output"/"post-packages"/f"{project}-post-packages.json",IMAGE_QA_OUTPUT_DIRECTORY/f"{project}-post-package-qa.json",IMAGE_QA_OUTPUT_DIRECTORY/f"{project}-branded-image-qa.json",IMAGE_QA_OUTPUT_DIRECTORY/f"{project}-creative-visual-qa.json",PROJECT_ROOT/"output"/"provenance"/f"{project}-provenance-audit.json",PROJECT_ROOT/"output"/"asset-intelligence"/f"{project}-asset-intelligence.json"]}
            input_paths=package_inputs[stage]
            if stage in {"caption-generator","alt-text-generator"}:
                from src.post_package.editorial_copy import copy_path
                input_paths.append(copy_path(PROJECT_ROOT,project))
            if stage=="content-grouping-analyzer":input_paths += [PROJECT_ROOT/"output"/"brand-composition-plans"/f"{project}-brand-composition-plans.json",IMAGE_QA_OUTPUT_DIRECTORY/f"{project}-branded-image-qa.json",IMAGE_QA_OUTPUT_DIRECTORY/f"{project}-creative-visual-qa.json",PROJECT_ROOT/"output"/"provenance"/f"{project}-provenance-audit.json"]
            if stage=="social-content-review":
                try:
                    review_packages=json.loads(input_paths[0].read_text(encoding="utf-8"));review_assets=json.loads(input_paths[-1].read_text(encoding="utf-8"));input_paths += [Path(x["image_path"]) for p in review_packages.get("packages",[]) for x in (p.get("slides") or [p.get("image",{})]) if x.get("image_path")];input_paths += [Path(x["source_path"]) for x in review_assets.get("assets",[]) if x.get("source_path") and Path(x["source_path"]).is_file()]
                except (OSError,ValueError,TypeError):pass
        elif stage in {"publishing-queue","scheduling-engine","publish-preflight","mock-platform-adapter","meta-platform-adapter","publication-manifest"}:
            pub=PROJECT_ROOT/"output"/"publishing";config=PROJECT_ROOT/"input"/"publishing"/"publishing-config.json";package=PROJECT_ROOT/"output"/"post-packages"/f"{project}-post-packages.json";queue=pub/f"{project}-publishing-queue.json";schedule=pub/f"{project}-schedule.json";preflight=pub/f"{project}-preflight.json";manifest=pub/f"{project}-publication-manifest.json"
            publishing_inputs={"publishing-queue":[package,IMAGE_QA_OUTPUT_DIRECTORY/f"{project}-post-package-qa.json",PROJECT_ROOT/"output"/"social-review"/f"{project}-social-review.json",PROJECT_ROOT/"output"/"provenance"/f"{project}-provenance-audit.json",PROJECT_ROOT/"input"/"brand"/"brand-config.json",config],"scheduling-engine":[queue,config],"publish-preflight":[queue,schedule,package,PROJECT_ROOT/"output"/"provenance"/f"{project}-provenance-audit.json",PROJECT_ROOT/"input"/"brand"/"brand-config.json"],"mock-platform-adapter":[queue,preflight,package,manifest],"meta-platform-adapter":[queue,preflight,package,manifest,PROJECT_ROOT/"input"/"publishing"/"meta-config.json"],"publication-manifest":[queue,schedule,preflight,manifest]}
            input_paths=publishing_inputs[stage]
            if stage in {"publishing-queue","publish-preflight","mock-platform-adapter","meta-platform-adapter"}:
                try:input_paths += [Path(x["image_path"]) for p in json.loads(package.read_text(encoding="utf-8")).get("packages",[]) for x in (p.get("slides") or [p.get("image",{})]) if x.get("image_path")]
                except (OSError,ValueError,TypeError):pass
        else:input_paths=[production_manifest]+([_artifact(IMAGE_QA_OUTPUT_DIRECTORY,project,"-image-qa")] if stage in {"production-manifest","review-gallery"} else [])
    stage_version = "3.0.0" if stage=="scene-planner" else "3.0.0" if stage in {"caption-generator","post-package-builder","post-package-qa","social-content-review"} else "3.1.0" if stage=="publishing-queue" else "1.2.0" if stage=="publish-preflight" else "2.2.0" if stage=="image-prompt-generator" else "2.0.0" if stage in {"creative-director","deterministic-image-processor"} else "20.3.1" if stage=="brand-composer" else "20.2.1" if stage=="branded-image-qa" else "1.2.0" if stage in {"content-grouping-analyzer","hashtag-generator","alt-text-generator","mock-platform-adapter","meta-platform-adapter","publication-manifest"} else "1.1.0" if stage in {"image-output-qa","review-gallery","creative-visual-qa","self-correction","provenance-audit","production-quality-report","release-manager"} else "1.0.0"
    stage_config={"platform_strategy":_PLATFORM_STRATEGY} if stage in PLATFORM_DEPENDENT_STAGES else {}
    from src.production.workflow import PROCESSOR_VERSION
    from src.publishing.foundation import PREFLIGHT_VERSION
    from src.content.visual_purpose import VERSION as VISUAL_PURPOSE_VERSION
    from src.branding.composer import BRANDED_QA_VERSION
    stage_version = {"deterministic-image-processor": PROCESSOR_VERSION,
                     "branded-image-qa": BRANDED_QA_VERSION,
                     "publish-preflight": PREFLIGHT_VERSION,
                     "image-processing-planner": "1.2.0"}.get(stage, stage_version)
    if stage in {"visual-art-director", "brand-composer", "content-grouping-analyzer",
                 "post-package-builder", "publishing-queue", "publish-preflight",
                 "mock-platform-adapter", "meta-platform-adapter"}:
        stage_config.update(project_ownership_contract="1.1.0",visual_purpose_version=VISUAL_PURPOSE_VERSION)
    if stage=="visual-art-director":
        from src.creative.visual_direction import VISUAL_DIRECTION_VERSION
        stage_version=VISUAL_DIRECTION_VERSION
    if stage=="scene-planner":
        from src.visual_assets.selection import SELECTION_VERSION
        stage_config["source_selection_version"]=SELECTION_VERSION
    if stage=="social-content-review":stage_config.update(social_review_version=REVIEW_VERSION,duplicate_detection_version=DUPLICATE_DETECTION_VERSION)
    if stage in {"content-grouping-analyzer","caption-generator","hashtag-generator","alt-text-generator","post-package-builder","post-package-qa"}:stage_config["languages"]=list(_REQUESTED_LANGUAGES)
    expected = cache.expected(stage, input_paths, module_version=stage_version, prompt_version=stage_version if stage in {"image-prompt-generator","creative-director","scene-planner"} else None,config=stage_config or None,
        model_policy=os.getenv("OPENAI_MODEL", "gpt-4o-mini") if stage in {"creative-director", "scene-planner"} else "deterministic-source-only" if stage == "image-prompt-generator" else "deterministic",semantic_json_inputs=stage=="brand-composer")
    cache_outputs = [existing] if existing else []
    if stage=="social-content-review" and existing:cache_outputs.append(PROJECT_ROOT/"output"/"social-review"/f"{project}-social-review.json")
    if stage == "image-prompt-generator" and existing:
        cache_outputs.append(IMAGE_PROMPTS_OUTPUT_DIRECTORY / f"{project}-prompt-manifest.json")
    cache_lookup_started=time.monotonic();valid, reason = cache.valid(stage, cache_outputs, expected);cache_lookup_ms=max(1,round((time.monotonic()-cache_lookup_started)*1000))
    if stage=="publishing-queue" and valid:
        reconciliation_reason=PublishingFoundation(project,PROJECT_ROOT,publish_target=_PUBLISH_TARGET).queue_reconciliation_reason()
        if reconciliation_reason:
            valid=False;reason=reconciliation_reason;logger.info("[MIGRATE] Publishing Queue - %s",reconciliation_reason)
    if valid and stage not in selection.forced:
        logger.info("[SKIP] %s - %s", _stage_display_name(stage), reason); cache.skip(stage, True)
        key = {"creative-director":"creative", "scene-planner":"scenes", "shot-planner":"shots"}.get(stage)
        cache.runtime_records[stage]["duration_ms"]=cache_lookup_ms
        cache.manifest["stage_records"]=[cache.runtime_records[name] for name in STAGE_ORDER if name in cache.runtime_records];cache.manifest["project_summary"]=cache.accounting_summary();cache._save()
        if key and existing: paths[key] = existing
        return True
    cache.begin(stage)
    if stage not in {"detail-preservation-enhancer", "deterministic-image-processor", "image-output-qa", "visual-art-director", "brand-composer", "branded-image-qa", "creative-visual-qa", "self-correction", "provenance-audit", "production-quality-report", "release-manager", "content-grouping-analyzer", "caption-generator","hashtag-generator","alt-text-generator","post-package-builder","post-package-qa","social-content-review","publishing-queue","scheduling-engine","publish-preflight","mock-platform-adapter","meta-platform-adapter","publication-manifest", "production-manifest", "review-gallery"}:
        logger.info("[RUN] %s", stage.replace("-", " ").title())
    if stage == "creative-director":
        result = run_legacy_creative_compat(CreativeDirectorAgent().run, knowledge, strategy, paths["content_plan"])
        if result is None: raise RuntimeError("Creative Director failed")
        paths["creative"] = result
    elif stage == "scene-planner":
        if "creative" not in paths: paths["creative"] = _artifact(CREATIVE_DIRECTIONS_OUTPUT_DIRECTORY, project, "-creative-directions")  # type: ignore[assignment]
        selection_path = plan_asset_selection(paths["content_plan"], inventory, review_root=PROJECT_ROOT)
        result = ScenePlanner().run(knowledge, paths["content_plan"], paths["creative"], selection_path, inventory)
        if result is None: raise RuntimeError("Scene Planner failed")
        paths["scenes"] = result
    elif stage == "shot-planner":
        if "creative" not in paths: paths["creative"] = _artifact(CREATIVE_DIRECTIONS_OUTPUT_DIRECTORY, project, "-creative-directions")  # type: ignore[assignment]
        if "scenes" not in paths: paths["scenes"] = _artifact(SCENE_PLANS_OUTPUT_DIRECTORY, project, "-scene-plans")  # type: ignore[assignment]
        result = ShotPlanner().run(knowledge, paths["creative"], paths["scenes"], inventory, paths["content_plan"])
        if result is None: raise RuntimeError("Shot Planner failed")
        paths["shots"] = result
    elif stage == "image-processing-planner":
        if "shots" not in paths: paths["shots"] = _artifact(SHOT_PLANS_OUTPUT_DIRECTORY, project, "-shot-plans")  # type: ignore[assignment]
        result = ImageProcessingPlanner().run(inventory, paths["shots"], source_manifest, content_plan_path=paths["content_plan"], knowledge_path=knowledge)
        if result is None: raise RuntimeError("Image Processing Planner failed")
        paths["processing"] = result
    elif stage == "image-prompt-generator":
        result = ImagePromptGenerator().run(project=project, processing_path=processing,
            asset_intelligence_path=intelligence, visual_inventory_path=inventory,
            knowledge_path=knowledge, content_path=paths["content_plan"], strategy_path=strategy,
            campaign_path=_artifact(CAMPAIGNS_OUTPUT_DIRECTORY, project, "-campaign-plan"),
            creative_path=_artifact(CREATIVE_DIRECTIONS_OUTPUT_DIRECTORY, project, "-creative-directions"),
            scene_path=_artifact(SCENE_PLANS_OUTPUT_DIRECTORY, project, "-scene-plans"), shot_path=shots,
            opportunities_path=_artifact(VISUAL_OPPORTUNITIES_OUTPUT_DIRECTORY, project, "-visual-opportunities"),
            source_manifest_path=source_manifest)
        output, manifest = result
        cache.complete(stage, [output, manifest], expected)
        return True
    elif stage == "detail-preservation-enhancer":
        logger.info("[RUN] Detail Preservation Enhancer")
        output,detail_qa=DetailPreservationEnhancer().run(project,prompt_file,intelligence);cache.complete(stage,[output,detail_qa],expected);return True
    elif stage == "deterministic-image-processor":
        logger.info("[RUN] Deterministic Image Processor")
        detail_manifest=DETAIL_ENHANCED_OUTPUT_DIRECTORY/project/"detail-enhancement-manifest.json"
        output=ProductionWorkflow(project).process(prompt_file,processing,inventory,intelligence,detail_manifest if detail_manifest.is_file() else None);cache.complete(stage,[output],expected);return True
    elif stage == "image-output-qa":
        logger.info("[RUN] Image Output QA")
        output=BrandComposer(project,PROJECT_ROOT).output_qa(force=stage in selection.forced);cache.complete(stage,[output],expected);return True
    elif stage == "visual-art-director":
        logger.info("[RUN] Visual Art Director")
        output=VisualArtDirectorWorkflow(project,PROJECT_ROOT).run();summary=json.loads(output.read_text(encoding="utf-8"))["summary"]
        logger.info("Visual Art Director completed: approved=%d requires_redirection=%d",summary["approved"],summary["requires_redirection"])
        cache.complete(stage,[output],expected);return True
    elif stage == "brand-composer":
        logger.info("[RUN] Brand Composer")
        logger.info("Verifying locked Brand Kit...\nReading eligible QA-passed images...\nBuilding composition plans...")
        composer=BrandComposer(project,PROJECT_ROOT);output=composer.compose(force=stage in selection.forced)
        summary=json.loads(output.read_text(encoding="utf-8"))["summary"]
        logger.info("Brand Composer completed:\n- Eligible images: %d\n- Branded images: %d\n- Skipped: %d\n- Layout fallbacks: %d\n- Missing optional phone omitted: %d\n- Missing optional email omitted: %d",summary["eligible_images"],summary["branded_images"],summary["skipped"],summary["layout_fallbacks"],summary["missing_optional_phone_omitted"],summary["missing_optional_email_omitted"])
        cache.complete(stage,[output],expected);return True
    elif stage=="social-content-review":
        logger.info("[RUN] Social Content Review\nBuilding visual content review dashboard...");dashboard=SocialContentReview(project,PROJECT_ROOT);output,companion=dashboard.render();summary=json.loads(companion.read_text(encoding="utf-8"));console_output=str(output).encode("ascii","backslashreplace").decode();logger.info("Social Content Review completed:\n- Packages: %d\n- Carousels: %d\n- Single posts: %d\n- Slides represented: %d\n- Source comparisons available: %d\n- Semantic warnings: %d\n- Duplicate warnings: %d\n- Provenance complete: %d/%d\n- Overall readiness: %s\n\nReview dashboard:\n%s",summary["package_count"],sum(x["package_type"]=="carousel" for x in summary["packages"]),sum(x["package_type"]=="single_post" for x in summary["packages"]),summary["slide_count"],summary["source_comparisons_available"],len(summary["semantic_warnings"]),len(summary["duplication_warnings"]),summary["provenance_completeness"]["complete"],summary["provenance_completeness"]["total"],summary["overall_readiness"],console_output);cache.complete(stage,[output,companion],expected);return True
    elif stage in {"publishing-queue","scheduling-engine","publish-preflight","mock-platform-adapter","meta-platform-adapter","publication-manifest"}:
        publishing=PublishingFoundation(project,PROJECT_ROOT,publish_target=_PUBLISH_TARGET);logger.info("[RUN] %s",_stage_display_name(stage))
        if stage=="publishing-queue":output=publishing.queue();summary=json.loads(output.read_text(encoding="utf-8"))["summary"];logger.info("Publishing Queue completed:\n- Platform publication jobs: %d\n- Active total: %d\n- Queued: %d\n- Scheduled: %d\n- Superseded: %d\n- Published: %d\n- Blocked: %d",summary["platform_publication_jobs"],summary["active_total"],summary["queued"],summary["scheduled"],summary["superseded"],summary["published"],summary["blocked"])
        elif stage=="scheduling-engine":output=publishing.schedule();payload=json.loads(output.read_text(encoding="utf-8"));summary=payload["summary"];logger.info("Scheduling Engine completed:\n- Mode: %s\n- Scheduled active: %d\n- Unscheduled active: %d\n- Superseded ignored: %d",payload["mode"],summary["scheduled_active"],summary["unscheduled_active"],summary["superseded_ignored"])
        elif stage=="publish-preflight":output=publishing.preflight();summary=json.loads(output.read_text(encoding="utf-8"))["summary"];logger.info("Publish Preflight completed:\n- Ready: %d\n- Ready with warnings: %d\n- Blocked: %d\n- Superseded skipped: %d\n- Cancelled skipped: %d\n- Already published skipped: %d",summary["ready"],summary["ready_with_warnings"],summary["blocked"],summary["superseded_skipped"],summary["cancelled_skipped"],summary["already_published_skipped"])
        elif stage=="mock-platform-adapter":output=publishing.mock_publish();payload=json.loads(output.read_text(encoding="utf-8"));run=payload.get("last_adapter_run",{});categories=run.get("skip_categories",{});logger.info("Mock Platform Adapter completed:\n- Preflight eligible current: %d\n- Existing successful simulations reused: %d\n- Superseded skipped: %d\n- Preflight blocked active: %d\n- Other skipped: %d\n- New adapter attempts: %d\n- New receipts: %d\n- External requests: 0",run.get("preflight_eligible",0),categories.get("existing_successful_simulation_reused",0),categories.get("superseded_skipped",0),categories.get("preflight_blocked_active",0),categories.get("other_skipped",0),run.get("adapter_attempted",0),run.get("receipts_generated",0))
        elif stage=="meta-platform-adapter":output=MetaInstagramAdapter(PROJECT_ROOT).publish_project(publishing);payload=json.loads(output.read_text(encoding="utf-8"));queue_state=json.loads(publishing.queue_path.read_text(encoding="utf-8"));logger.info("Meta Platform Adapter completed:\n- Real receipts: %d\n- Published: %d\n- Blocked: %d",len(payload.get("real_receipts",[])),sum(x.get("status") in {"published","published_with_warnings"} for x in queue_state.get("items",[])),sum(x.get("status")=="blocked" for x in queue_state.get("items",[])))
        else:output=publishing.manifest();payload=json.loads(output.read_text(encoding="utf-8"));historical=payload.get("historical_totals",{});state=payload.get("current_state",{});current=payload.get("current_run",{});logger.info("Publication Manifest completed:\nHistorical totals:\n- Queue records: %d\n- Receipts: %d\n- History entries: %d\nCurrent state:\n- Active jobs: %d\n- Superseded jobs: %d\nCurrent run:\n- Preflight eligible: %d\n- Existing simulations reused: %d\n- Adapter attempts: %d\n- Adapter skips: %d\n- New receipts: %d",historical.get("total_queue_records",0),historical.get("total_receipts",0),historical.get("total_history_entries",0),state.get("active_jobs",0),state.get("superseded_jobs",0),current.get("preflight_eligible",0),current.get("existing_successful_simulations_reused",0),current.get("adapter_attempts",0),current.get("adapter_skips",0),current.get("new_receipts_generated",0))
        cache.complete(stage,[output],expected);return True
    elif stage == "branded-image-qa":
        logger.info("[RUN] Branded Image QA")
        logger.info("Validating branding and source preservation...")
        composer=BrandComposer(project,PROJECT_ROOT);output=composer.qa(force=stage in selection.forced);summary=json.loads(output.read_text(encoding="utf-8"))["summary"]
        logger.info("Branded Image QA completed:\n- Exceptional: %d\n- Production ready: %d\n- Ready with warnings: %d\n- Manual review: %d\n- Failed: %d\n- Average QA score: %s/100",summary["exceptional"],summary["production_ready"],summary["production_ready_with_warnings"],summary["manual_review_required"],summary["failed"],summary["average_qa_score"])
        cache.complete(stage,[output,composer.manifest_path,composer.gallery_path],expected);return True
    elif stage in {"creative-visual-qa","self-correction","provenance-audit","production-quality-report","release-manager"}:
        pipeline=HardeningPipeline(project,PROJECT_ROOT)
        labels={"creative-visual-qa":"Creative Visual QA","self-correction":"Automatic Self-Correction","provenance-audit":"Provenance Audit","production-quality-report":"Production Quality Report","release-manager":"Release Manager"}
        logger.info("[RUN] %s",labels[stage])
        if stage=="creative-visual-qa":output=pipeline.creative_qa(force=stage in selection.forced)
        elif stage=="self-correction":output=pipeline.self_correct(force=stage in selection.forced)
        elif stage=="provenance-audit":output=pipeline.provenance_audit(force=stage in selection.forced)
        elif stage=="production-quality-report":output=pipeline.quality_report(force=stage in selection.forced)
        else:
            output=pipeline.release(force=stage in selection.forced);release_summary=json.loads(output.read_text(encoding="utf-8")).get("summary",{})
            logger.info("Release Manager completed:\n- Eligible branded inputs: %d\n- Released items: %d\n- Excluded: %d",release_summary.get("eligible_branded_inputs",0),release_summary.get("released_items",0),release_summary.get("excluded_items",0))
        cache.complete(stage,[output],expected);return True
    elif stage in {"content-grouping-analyzer","caption-generator","hashtag-generator","alt-text-generator","post-package-builder","post-package-qa"}:
        pipeline=PostPackagePipeline(project,PROJECT_ROOT,_REQUESTED_LANGUAGES);logger.info("[RUN] %s",_stage_display_name(stage))
        if stage=="content-grouping-analyzer":logger.info("Grouping branded creatives into posts and carousels...");output=pipeline.groups();summary=json.loads(output.read_text(encoding="utf-8"))["summary"];logger.info("Content Grouping completed:\n- Branded inputs considered: %d\n- Grouped items: %d\n- Excluded items: %d\n- Single posts: %d\n- Carousels: %d\n- Story sequences: %d\n- Exclusions by reason: %s\n- Duplicate packages prevented: %d",summary["branded_inputs_considered"],summary["grouped_items"],summary["excluded_items"],summary["single_post"],summary["carousel"],summary["story_sequence"],json.dumps(summary["exclusions_by_reason"],ensure_ascii=False),summary["duplicate_packages_prevented"])
        elif stage=="caption-generator":logger.info("Retrieving relevant verified facts...\nGenerating customer-facing captions...");output=pipeline.captions();summary=json.loads(output.read_text(encoding="utf-8"))["summary"];logger.info("Caption Generator completed:\n- Captions created: %d\n- Carousel master captions: %d\n- Visual-only captions: %d\n- Fact-grounded captions: %d",summary["captions_created"],summary["carousel_master_captions"],summary["visual_only_captions"],summary["fact_grounded_captions"])
        elif stage=="hashtag-generator":logger.info("Generating platform-specific hashtags...");output=pipeline.hashtags();logger.info("Hashtag sets created: %d",_read_count(output,"items"))
        elif stage=="alt-text-generator":logger.info("Generating visually grounded alt text...");output=pipeline.alt_text();logger.info("Alt text items created: %d",_read_count(output,"items"))
        elif stage=="post-package-builder":logger.info("Assembling final social post packages...");output=pipeline.build();logger.info("Post packages created: %d",_read_count(output,"packages"))
        else:
            logger.info("Validating factual accuracy, platform fit, and provenance...");output=pipeline.qa();summary=json.loads(output.read_text(encoding="utf-8"))["summary"];score="no content" if summary["average_score"] is None else f'{summary["average_score"]}/100';logger.info("Post Package QA completed:\n- Status: %s\n- Exceptional: %d\n- Ready: %d\n- Ready with warnings: %d\n- Blocked: %d\n- Average score: %s",summary["status"],summary["exceptional"],summary["ready"],summary["ready_with_warnings"],summary["blocked"],score)
        cache.complete(stage,[output],expected);return True
    elif stage == "production-manifest":
        logger.info("[RUN] Production Manifest")
        output=ProductionWorkflow(project).finalize_manifest();cache.complete(stage,[output],expected);return True
    elif stage == "review-gallery":
        logger.info("[RUN] Review Gallery")
        output=ProductionWorkflow(project).gallery();cache.complete(stage,[output],expected);return True
    else: return True
    output = result
    cache.complete(stage, [output], expected)
    return True


def _process_project(project: ProjectInput) -> bool:
    """Process one project through the authoritative Department 1 -> 2 contract."""
    classifier = DocumentClassifier()
    document_analysis: list[dict[str, object]] = []

    # Image-only projects have no textual Department 2 knowledge to extract.
    if not project.pdf_files and not project.auxiliary_files:
        for image_path in project.image_files:
            classification = classifier.classify(image_path.name, "")
            document_analysis.append(
                analyze_document(image_path, "", classification, project.name)
            )
        try:
            report_path = save_document_analysis(
                project.name, document_analysis, project.warnings
            )
            logger.warning(
                "Content identity remains ambiguous; analysis saved: %s",
                report_path.relative_to(PROJECT_ROOT),
            )
        except OSError as error:
            logger.error("Could not save document analysis: %s", error)
            return False
        return True

    source_paths = [
        *project.pdf_files,
        *project.auxiliary_files,
        *project.image_files,
    ]
    folder_root = INPUT_DIRECTORY / project.name
    project_root = folder_root if folder_root.is_dir() else INPUT_DIRECTORY
    handoff_root = PROJECT_ROOT / "output" / "department1"
    legacy_handoff_path = handoff_root / re.sub(
        r"[^\w.-]+", "-", project.name.strip(), flags=re.UNICODE
    ).strip("-._") / "department2-handoff.json"
    handoff_path = handoff_root / project_storage_key(project.name) / "department2-handoff.json"
    # Read old handoffs only through the signed owner/hash validator below.
    candidate_handoff_path = handoff_path if handoff_path.is_file() else legacy_handoff_path

    # Reuse a Department 1 handoff only when its signed payload and every
    # current source hash still match. Otherwise rebuild Department 1.
    handoff = None
    if candidate_handoff_path.is_file():
        try:
            handoff = load_department2_handoff(
                candidate_handoff_path,
                expected_project=project.name,
                project_root=project_root,
                verify_source_hashes=True,
                source_paths=source_paths,
            )
            current_rel = {
                str(path.resolve().relative_to(project_root.resolve())).replace("\\", "/")
                for path in source_paths
            }
            if current_rel != set(handoff.source_hashes):
                raise Department2HandoffError(
                    "Department 1 source inventory changed after handoff."
                )
            logger.info(
                "Using validated Department 1 handoff: %s",
                candidate_handoff_path.relative_to(PROJECT_ROOT),
            )
        except (Department2HandoffError, OSError, ValueError) as error:
            logger.warning("Department 1 handoff is stale/invalid: %s", error)
            handoff = None

    if handoff is None:
        logger.info("Running authoritative Department 1 for '%s'...", project.name)
        try:
            Department1Pipeline(
                project_root,
                project_name=project.name,
                output_root=handoff_root,
                source_paths=source_paths,
            ).run()
            handoff = load_department2_handoff(
                handoff_path,
                expected_project=project.name,
                project_root=project_root,
                verify_source_hashes=True,
                source_paths=source_paths,
            )
        except (Department1Error, Department2HandoffError, OSError, ValueError) as error:
            logger.error("Department 1 -> 2 handoff failed: %s", error)
            return False

    logger.info(
        "Department 2 consuming %d provenance-preserving Department 1 source(s)...",
        len(handoff.sources),
    )
    document_knowledge: list[tuple[ProjectKnowledge, DocumentType, Path]] = []
    temporary_directory = KNOWLEDGE_OUTPUT_DIRECTORY / project.name / "documents"
    evidence_directory = MARKDOWN_OUTPUT_DIRECTORY / project.name
    agent = KnowledgeAgent()

    for source in handoff.sources:
        # Images remain authentic visual evidence, but they are not sent through
        # the text knowledge extractor as empty pseudo-documents.
        if source.source_type == "image":
            continue
        extracted_text = source.text()
        if not extracted_text.strip():
            logger.warning("No textual evidence in Department 1 source: %s", source.relative_path)
            continue

        source_path = project_root / source.relative_path
        markdown_path = write_source_markdown(source, evidence_directory)
        classification = classifier.classify(source.filename, extracted_text)
        document_analysis.append(
            analyze_document(source_path, extracted_text, classification, project.name)
        )
        document_type = classification.document_type
        logger.info(
            "D2 classification for %s: %s | Reason: %s | Confidence: %.0f%%",
            source.filename,
            document_type.value,
            classification.reason,
            classification.confidence * 100,
        )
        try:
            temporary_directory.mkdir(parents=True, exist_ok=True)
            metadata_path = temporary_directory / f"{Path(source.filename).stem}-classification.json"
            metadata = classification.to_dict()
            metadata["department1_source_id"] = source.source_id
            metadata["department1_source_sha256"] = source.sha256
            metadata["department1_handoff_sha256"] = handoff.handoff_sha256
            metadata_path.write_text(
                json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
            )
        except OSError as error:
            logger.error(
                "Could not save classification metadata for '%s': %s",
                source.filename,
                error,
            )
            return False

        temporary_path = agent.run(
            markdown_path,
            output_directory=temporary_directory,
            output_filename=f"{Path(source.filename).stem}-{source.source_id}",
            source_document=source.relative_path,
            source_project=project.name,
            source_id=source.source_id,
            source_sha256=source.sha256,
        )
        if temporary_path is None:
            logger.error("Knowledge extraction failed for '%s'.", source.filename)
            return False

        try:
            knowledge = ProjectKnowledge.from_json(
                temporary_path.read_text(encoding="utf-8")
            )
            knowledge.commercial_intelligence = extract_document_intelligence(
                source.markdown(),
                project=project.name,
                source_file=source.relative_path,
                document_type=document_type,
                classification_confidence=classification.confidence,
                source_id=source.source_id,
                source_sha256=source.sha256,
            )
            document_knowledge.append((knowledge, document_type, temporary_path))
        except (OSError, ValueError) as error:
            logger.error(
                "Could not read temporary knowledge for '%s': %s",
                source.filename,
                error,
            )
            return False

    if not document_knowledge:
        logger.error(
            "Department 2 received no usable textual evidence from the validated Department 1 handoff."
        )
        return False

    for image_path in project.image_files:
        classification = classifier.classify(image_path.name, "")
        document_analysis.append(analyze_document(image_path, "", classification, project.name))
    try:
        analysis_path = save_document_analysis(project.name, document_analysis, project.warnings)
        logger.info("Document analysis saved: %s", analysis_path.relative_to(PROJECT_ROOT))
    except OSError as error:
        logger.error("Could not save document analysis: %s", error)
        return False

    merged, conflicts = fuse_knowledge(document_knowledge, project_namespace=project.name)
    for conflict in conflicts:
        logger.warning("Knowledge fusion conflict: %s", conflict)
    try:
        knowledge_path = save_project_knowledge(merged, project.name)
    except (OSError, ValueError) as error:
        logger.error("Could not save merged knowledge JSON: %s", error)
        return False
    logger.info("Merged knowledge saved: %s", knowledge_path.relative_to(PROJECT_ROOT))
    logger.info("Running Knowledge Evaluation...")
    try:
        evaluator = KnowledgeEvaluator()
        evaluation = evaluator.evaluate_file(knowledge_path)
        report_path = evaluator.save_report(evaluation, knowledge_path)
    except Exception as error:
        logger.error("Knowledge evaluation failed: %s", error)
        return False
    logger.info("Evaluator version: %s", evaluation.evaluator_version)
    logger.info("Overall Score: %s/100", evaluation.overall_score)
    logger.info("Completeness: %s%%", evaluation.completeness_percentage)
    logger.info("Report saved: %s", report_path.relative_to(PROJECT_ROOT))
    if not evaluation.json_validity["valid"]:
        logger.error("Knowledge evaluation found invalid JSON: %s", evaluation.json_validity["error"])
        return False

    # Auxiliary-only projects have no authentic visual source to process.
    if not project.pdf_files and not project.image_files:
        return True

    logger.info("Extracting and inventorying authentic source images...")
    try:
        source_manifest_path = extract_visual_assets(project.name, project.pdf_files, project.image_files)
        integrity_failures = verify_source_integrity(source_manifest_path)
        if integrity_failures:
            raise ValueError("Source image integrity failed: " + ", ".join(integrity_failures))
        visual_analysis_path = analyze_visual_assets(source_manifest_path)
        intelligence_result = AssetIntelligenceAgent().run(source_manifest_path, knowledge_path)
        if intelligence_result is None:
            raise ValueError("Asset Intelligence did not produce its required output contract")
    except Exception as error:
        logger.error("Source visual processing failed: %s", error)
        return False
    logger.info("Source visuals analyzed: %s", visual_analysis_path)
    logger.info("Asset intelligence saved: %s", intelligence_result)
    return True


def _validate_forced_prerequisites(stage: str, project: str, cache: StageCache) -> tuple[bool, str | None]:
    """Validate and report direct prerequisite artifacts without executing them."""
    from src.utils.config import (VISUAL_INVENTORY_OUTPUT_DIRECTORY, VISUAL_OPPORTUNITIES_OUTPUT_DIRECTORY, CREATIVE_INTELLIGENCE_OUTPUT_DIRECTORY,
                                  SOURCE_IMAGES_OUTPUT_DIRECTORY)
    releases=sorted((PROJECT_ROOT/"output"/"releases"/project).glob("release-*/manifest.json"))
    artifact_by_stage: dict[str, Path | None] = {
        "discover": PROJECT_ROOT / "input",
        "document-analysis": _artifact(REPORTS_OUTPUT_DIRECTORY, project, "-document-analysis"),
        "text-extraction": _artifact(MARKDOWN_OUTPUT_DIRECTORY, project, ""),
        "knowledge-extraction": _artifact(KNOWLEDGE_OUTPUT_DIRECTORY, project, ""),
        "knowledge-fusion": _artifact(KNOWLEDGE_OUTPUT_DIRECTORY, project, ""),
        "knowledge-evaluation": _artifact(REPORTS_OUTPUT_DIRECTORY, project, "-knowledge-evaluation"),
        "visual-extraction": SOURCE_IMAGES_OUTPUT_DIRECTORY / project / "manifest.json",
        "asset-intelligence": _artifact(ASSET_INTELLIGENCE_OUTPUT_DIRECTORY, project, "-asset-intelligence"),
        "source-image-ranking": SOURCE_IMAGE_RANKING_OUTPUT_DIRECTORY/f"source-image-ranking-{_ranking_folder(project)}.json",
        "project-brand-identity": SOURCE_IMAGE_RANKING_OUTPUT_DIRECTORY/f"project-brand-{_ranking_folder(project)}.json",
        "branded-content": SOURCE_IMAGE_RANKING_OUTPUT_DIRECTORY/f"branded-content-{_ranking_folder(project)}.json",
        "visual-inventory": _artifact(VISUAL_INVENTORY_OUTPUT_DIRECTORY, project, "-visual-inventory"),
        "creative-intelligence": _artifact(CREATIVE_INTELLIGENCE_OUTPUT_DIRECTORY, project, "-creative-opportunity-map"),
        "marketing-strategy": _artifact(STRATEGY_OUTPUT_DIRECTORY, project, "-strategy"),
        "visual-opportunities": _artifact(VISUAL_OPPORTUNITIES_OUTPUT_DIRECTORY, project, "-visual-opportunities"),
        "campaign-planner": _artifact(CAMPAIGNS_OUTPUT_DIRECTORY, project, "-campaign-plan"),
        "content-planner": _artifact(CONTENT_OUTPUT_DIRECTORY, project, "-content-plan"),
        "creative-director": _artifact(CREATIVE_DIRECTIONS_OUTPUT_DIRECTORY, project, "-creative-directions"),
        "scene-planner": _artifact(SCENE_PLANS_OUTPUT_DIRECTORY, project, "-scene-plans"),
        "shot-planner": _artifact(SHOT_PLANS_OUTPUT_DIRECTORY, project, "-shot-plans"),
        "image-processing-planner": _artifact(IMAGE_PROCESSING_PLANS_OUTPUT_DIRECTORY, project, "-image-processing-plans"),
        "image-prompt-generator": _artifact(IMAGE_PROMPTS_OUTPUT_DIRECTORY, project, "-image-prompts"),
        "detail-preservation-enhancer": DETAIL_ENHANCED_OUTPUT_DIRECTORY / project / "detail-enhancement-manifest.json",
        "deterministic-image-processor": _artifact(PRODUCTION_MANIFESTS_OUTPUT_DIRECTORY, project, "-production-manifest"),
        "image-output-qa": IMAGE_QA_OUTPUT_DIRECTORY/f"{project}-image-qa.json",
        "visual-art-director": VISUAL_DIRECTIONS_OUTPUT_DIRECTORY/f"{project}-visual-direction-contracts.json",
        "brand-composer": PROJECT_ROOT / "output" / "brand-composition-plans" / f"{project}-brand-composition-plans.json",
        "branded-image-qa": IMAGE_QA_OUTPUT_DIRECTORY / f"{project}-branded-image-qa.json",
        "creative-visual-qa": IMAGE_QA_OUTPUT_DIRECTORY / f"{project}-creative-visual-qa.json",
        "self-correction": PROJECT_ROOT / "output" / "corrections" / f"{project}-self-correction-log.json",
        "provenance-audit": PROJECT_ROOT / "output" / "provenance" / f"{project}-provenance-audit.json",
        "production-quality-report": PROJECT_ROOT / "output" / "reports" / f"{project}-production-quality-report.json",
        "release-manager": releases[-1] if releases else None,
        "social-content-review": PROJECT_ROOT/"output"/"social-review"/f"{project}-social-review.html",
        "content-grouping-analyzer": PROJECT_ROOT/"output"/"content-groups"/f"{project}-content-groups.json",
        "caption-generator": PROJECT_ROOT/"output"/"captions"/f"{project}-captions.json",
        "hashtag-generator": PROJECT_ROOT/"output"/"hashtags"/f"{project}-hashtags.json",
        "alt-text-generator": PROJECT_ROOT/"output"/"alt-text"/f"{project}-alt-text.json",
        "post-package-builder": PROJECT_ROOT/"output"/"post-packages"/f"{project}-post-packages.json",
        "post-package-qa": IMAGE_QA_OUTPUT_DIRECTORY/f"{project}-post-package-qa.json",
        "production-manifest": _artifact(PRODUCTION_MANIFESTS_OUTPUT_DIRECTORY, project, "-production-manifest"),
    }
    reused: list[str] = []
    for prerequisite in DEPENDENCIES.get(stage, ()):
        path = artifact_by_stage.get(prerequisite)
        if path is None or not path.exists(): return False, f"required prerequisite '{prerequisite}' is missing ({path or 'artifact unresolved'})"
        if path.suffix.casefold() == ".json":
            try: payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error: return False, f"required prerequisite '{prerequisite}' is corrupted: {error}"
            if prerequisite == "brand-composer":
                for item in payload.get("plans", []):
                    branded = Path(str(item.get("branded_image_path", "")))
                    if not branded.is_absolute(): branded = PROJECT_ROOT / branded
                    if not branded.is_file(): return False, f"required prerequisite 'brand-composer' has a missing branded image: {branded}"
                    if item.get("branded_image_hash") and sha256_file(branded) != item["branded_image_hash"]:
                        return False, f"required prerequisite 'brand-composer' has a stale branded image hash: {branded}"
            if prerequisite == "deterministic-image-processor":
                for item in payload.get("items", []):
                    produced = Path(str(item.get("output_path", "")))
                    if not produced.is_absolute(): produced = PROJECT_ROOT / produced
                    if not produced.is_file(): return False, f"required prerequisite 'deterministic-image-processor' has a missing produced image: {produced}"
                    if item.get("output_hash") and sha256_file(produced) != item["output_hash"]:
                        return False, f"required prerequisite 'deterministic-image-processor' has a stale produced image hash: {produced}"
        if cache.manifest.get("stage_statuses", {}).get(prerequisite) == "stale":
            return False, f"required prerequisite '{prerequisite}' is stale"
        logger.info("[SKIP] %s - valid prerequisite artifact", _stage_display_name(prerequisite))
        cache.reuse_prerequisite(prerequisite,path)
        reused.append(prerequisite)
    cache.manifest["upstream_artifacts_reused"] = reused
    cache._save()
    return True, None
def _log_project_warning_summary(project_name: str, manifest_path: Path, valid_content_ideas: int) -> None:
    """Print a non-fatal per-project source/content completion summary."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        extraction = manifest.get("extraction_summary", {})
        availability_path = REPORTS_OUTPUT_DIRECTORY / f"{project_name}-content-availability.json"
        availability = json.loads(availability_path.read_text(encoding="utf-8")) if availability_path.exists() else {}
        skipped = availability.get("summary", {}).get("skipped_unavailable", 0)
        logger.info(
            "Project completed with warnings:\n- extracted images: %d\n- failed image extractions: %d\n- valid content ideas: %d\n- skipped unavailable ideas: %d",
            extraction.get("extracted_images", len(manifest.get("assets", []))),
            extraction.get("failed_image_extractions", len(manifest.get("extraction_failures", []))),
            valid_content_ideas,
            skipped,
        )
    except (OSError, TypeError, ValueError):
        logger.warning("Project completed, but its warning summary could not be read.")


if __name__ == "__main__":
    sys.exit(main())

# DEPARTMENT3_PHASE4C_LIVE_BRIDGE
# Canonical Department 3 live strategy boundary.
# Advisory engines may contribute intelligence, but only this bridge may convert
# candidates into an Approved Content Plan.
def _department3_canonical_approve(
    *,
    project_id,
    candidates,
    creative_engine=None,
    creative_args=(),
    creative_kwargs=None,
    campaign_engine=None,
    campaign_args=(),
    campaign_kwargs=None,
):
    return LiveDepartment3Orchestrator().approve(
        project_id=project_id,
        candidates=candidates,
        creative_engine=creative_engine,
        creative_args=creative_args,
        creative_kwargs=creative_kwargs or {},
        campaign_engine=campaign_engine,
        campaign_args=campaign_args,
        campaign_kwargs=campaign_kwargs or {},
    )

