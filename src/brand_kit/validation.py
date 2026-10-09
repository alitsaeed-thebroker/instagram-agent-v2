"""Validation for the stable brand configuration schema."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
RATIO = re.compile(r"^[1-9]\d*:[1-9]\d*$")
SUPPORTED_SCHEMAS = {"1.0.0", "1.1.0"}
SOURCE_STATUSES = {"official_confirmed", "logo_derived", "system_selected", "user_confirmed", "missing", "invalid"}


@dataclass(frozen=True)
class ValidationResult:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors

    @property
    def status(self) -> str:
        return "invalid" if self.errors else "valid with warnings" if self.warnings else "valid"


def validate_brand_config(config: Any) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(config, dict):
        return ValidationResult(("Configuration must be a JSON object.",), ())
    required = ("schema_version", "brand_id", "company", "brand_voice", "visual_identity", "content_rules", "platform_defaults", "approval")
    for key in required:
        if key not in config: errors.append(f"Missing required field: {key}")
    if config.get("schema_version") not in SUPPORTED_SCHEMAS: errors.append("Unsupported schema_version.")
    company = config.get("company", {})
    if not isinstance(company, dict): errors.append("company must be an object."); company = {}
    if not isinstance(company.get("official_name"), str) or not company.get("official_name", "").strip(): errors.append("company.official_name must not be empty.")
    if not isinstance(company.get("website"), str) or not company.get("website", "").strip(): errors.append("company.website must be valid text.")
    if not isinstance(company.get("phone_numbers"), list): errors.append("company.phone_numbers must be an array.")
    elif not company["phone_numbers"]: warnings.append("No confirmed phone number is configured.")
    if not isinstance(company.get("email_addresses"), list): errors.append("company.email_addresses must be an array.")
    elif not company["email_addresses"]: warnings.append("No confirmed email address is configured.")
    visual = config.get("visual_identity", {})
    if not isinstance(visual, dict): errors.append("visual_identity must be an object."); visual = {}
    colors = visual.get("colors", {})
    if not isinstance(colors, dict): errors.append("visual_identity.colors must be an object."); colors = {}
    for name in ("primary", "secondary", "accent", "background_light", "background_dark", "text_light", "text_dark"):
        value = colors.get(name)
        if isinstance(value, dict):
            if value.get("status") not in SOURCE_STATUSES: errors.append(f"visual_identity.colors.{name}.status is invalid.")
            value = value.get("value")
        if value is not None and (not isinstance(value, str) or not HEX.fullmatch(value)): errors.append(f"visual_identity.colors.{name} must contain a six-digit hex color or null.")
    if colors.get("status") == "unconfirmed": warnings.append("Brand colors are unconfirmed.")
    policy = visual.get("logo_policy", {})
    if not isinstance(policy, dict): errors.append("visual_identity.logo_policy must be an object."); policy = {}
    if policy.get("status") not in {"missing", "available"}: errors.append("logo_policy.status must be missing or available.")
    for key in ("allow_recoloring", "allow_distortion", "allow_cropping", "allow_rotation", "allow_effects"):
        if policy.get(key) is not False: errors.append(f"Unsafe logo transformation must remain disabled: {key}.")
    if not isinstance(policy.get("minimum_width_px"), int) or isinstance(policy.get("minimum_width_px"), bool) or policy.get("minimum_width_px", 0) <= 0: errors.append("logo_policy.minimum_width_px must be a positive integer.")
    clear_space = policy.get("minimum_clear_space_ratio")
    if not isinstance(clear_space, (int, float)) or isinstance(clear_space, bool) or not 0 <= clear_space <= 1: errors.append("logo_policy.minimum_clear_space_ratio must be between 0 and 1.")
    if policy.get("preserve_transparency") is not True: errors.append("logo_policy.preserve_transparency must remain enabled.")
    if policy.get("status") == "available" and not isinstance(policy.get("preferred_logo_id"), str): errors.append("An available logo requires preferred_logo_id.")
    if policy.get("status") == "missing": warnings.append("Official logo is missing.")
    typography = visual.get("typography", {})
    if isinstance(typography, dict) and typography.get("status") == "system_defaults": warnings.append("Typography uses system-default fonts.")
    if isinstance(typography, dict) and typography.get("status") not in {"system_defaults", "system_selected", "official_confirmed", "user_confirmed"}: errors.append("visual_identity.typography.status is invalid.")
    if not isinstance(typography, dict): errors.append("visual_identity.typography must be an object.")
    elif typography.get("allow_unapproved_font_files") is not False: errors.append("Unapproved font files must remain disabled.")
    rules = config.get("content_rules", {})
    languages = rules.get("supported_languages") if isinstance(rules, dict) else None
    if not isinstance(languages, list) or not languages: errors.append("content_rules.supported_languages must be a non-empty array.")
    platforms = config.get("platform_defaults", {})
    if not isinstance(platforms, dict) or not platforms: errors.append("platform_defaults must be a non-empty object.")
    else:
        for name, item in platforms.items():
            if not isinstance(item, dict): errors.append(f"platform_defaults.{name} must be an object."); continue
            for dimension in ("width", "height"):
                value = item.get(dimension)
                if not isinstance(value, int) or isinstance(value, bool) or value <= 0: errors.append(f"platform_defaults.{name}.{dimension} must be a positive integer.")
            if not isinstance(item.get("aspect_ratio"), str) or not RATIO.fullmatch(item.get("aspect_ratio", "")): errors.append(f"platform_defaults.{name}.aspect_ratio is invalid.")
    approval = config.get("approval", {})
    if not isinstance(approval, dict): errors.append("approval must be an object.")
    elif approval.get("status") not in {"draft", "reviewed", "approved", "revoked"}: errors.append("approval.status is invalid.")
    if isinstance(approval, dict) and approval.get("status") == "draft": warnings.append("Brand configuration approval is draft.")
    return ValidationResult(tuple(errors), tuple(dict.fromkeys(warnings)))
