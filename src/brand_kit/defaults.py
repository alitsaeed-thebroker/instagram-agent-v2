"""Canonical, conservative defaults for the Domus Erbil global brand kit."""

DEFAULT_BRAND_CONFIG = {
    "schema_version": "1.0.0",
    "brand_id": "domus-erbil",
    "company": {
        "official_name": "Domus Erbil Company for Real Estate",
        "display_name": "Domus Erbil",
        "website": "domuserbil.com",
        "phone_numbers": [], "email_addresses": [], "social_handles": {}, "address": None,
    },
    "brand_voice": {
        "positioning": "Professional real-estate advisory and brokerage",
        "tone": ["professional", "clear", "trustworthy", "premium", "modern"],
        "avoid": ["unsupported investment guarantees", "exaggerated claims", "fabricated scarcity", "unverified prices", "unverified returns"],
    },
    "visual_identity": {
        "logo_policy": {
            "status": "missing", "preferred_logo_id": None,
            "minimum_clear_space_ratio": 0.1, "minimum_width_px": 120,
            "allow_recoloring": False, "allow_distortion": False, "allow_cropping": False,
            "allow_rotation": False, "allow_effects": False, "preserve_transparency": True,
        },
        "colors": {
            "status": "unconfirmed", "primary": None, "secondary": None, "accent": None,
            "background_light": "#FFFFFF", "background_dark": "#111111",
            "text_light": "#FFFFFF", "text_dark": "#111111",
        },
        "typography": {
            "status": "system_defaults", "primary_font": "Arial", "secondary_font": "Georgia",
            "fallback_fonts": ["Arial", "Helvetica", "Segoe UI", "sans-serif"],
            "allow_unapproved_font_files": False,
        },
        "layout_style": {
            "style": "premium_minimal", "maximum_text_blocks": 3, "maximum_headline_lines": 2,
            "minimum_safe_margin_ratio": 0.05, "prefer_negative_space": True,
            "allow_gradient_panel": True, "allow_solid_information_panel": True,
            "allow_text_over_critical_architecture": False,
        },
    },
    "content_rules": {
        "supported_languages": ["English", "Arabic", "Kurdish Sorani"], "default_language": "English",
        "require_verified_project_facts": True, "require_source_references": True,
        "allow_unverified_claims": False, "allow_price_without_source": False,
        "allow_payment_plan_without_source": False, "allow_roi_without_source": False,
    },
    "platform_defaults": {
        "instagram_feed": {"width": 1080, "height": 1350, "aspect_ratio": "4:5"},
        "instagram_square": {"width": 1080, "height": 1080, "aspect_ratio": "1:1"},
        "instagram_story": {"width": 1080, "height": 1920, "aspect_ratio": "9:16"},
        "facebook_portrait": {"width": 1200, "height": 1500, "aspect_ratio": "4:5"},
        "linkedin_square": {"width": 1200, "height": 1200, "aspect_ratio": "1:1"},
    },
    "approval": {
        "status": "draft", "approved_by": None, "approved_at": None,
        "notes": [
            "Add the official Domus Erbil logo to input/brand/logos/", "Confirm official phone numbers",
            "Confirm official brand colors", "Confirm approved fonts before production branding",
        ],
    },
}
