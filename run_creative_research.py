"""Run the deliberately small Phase 3 public-source validation batch."""
from pathlib import Path
from src.creative_research import CreativeResearchEngine,ResearchDocument,ResearchObjective
from src.utils.config import PROJECT_ROOT

SOURCES=[
 ResearchDocument("https://www.behance.net/gallery/248522313/Luxury-Real-Estate-Campaign","behance.net","professional_portfolio","Mohamed Alaa Younes","behance","real estate","luxury real estate hero","Architecture-first hero, interior and lifestyle sequence. Image dominant, minimal hierarchy, strong visual hierarchy and consistent tone.","2026-04-30",84,94,82,trust_level="MEDIUM"),
 ResearchDocument("https://www.adamsdesignboston.com/projects/stratus-residences-brand-identity-boston/","adamsdesignboston.com","agency_case_study","Adams Design","website","real estate","luxury real estate hero","Conceptual editorial architecture campaign uses atmosphere, openness and horizon imagery. Architecture first, editorial hierarchy, negative space.",None,92,94,90,trust_level="HIGH"),
 ResearchDocument("https://www.thevoydesign.com/portfolio/cassiathea-hotel-branding","thevoydesign.com","agency_case_study","The Voy Design","website","luxury hospitality","luxury real estate hero","Quiet luxury hospitality identity keeps architecture, light and texture central. Minimal hierarchy, negative space, restrained brand presence and editorial typography.","2025-01-01",90,82,90,trust_level="HIGH"),
 ResearchDocument("https://www.cruxdesignagency.co.uk/work/branding-marketing-for-a-contemporary-surrey-development","cruxdesignagency.co.uk","agency_case_study","Crux Design Agency","website","real estate","premium developer campaign","Cohesive development system connects brochure, detailed floor plans, site layouts, maps and photography. Context, detail, proof and consistent brand behavior.",None,92,92,88,trust_level="HIGH"),
 ResearchDocument("https://www.studiothink.com/portfolio/park-and-maven/","studiothink.com","agency_case_study","Studiothink","website","real estate","unit layout presentation","Buyer journey uses brochures and floor-plan sheets to guide understanding. Complete plan, technical typography, clean technical information and proof.",None,88,92,86,trust_level="HIGH"),
 ResearchDocument("https://brightcreativeagency.com/case-studies/hill-brand-development","brightcreativeagency.com","agency_case_study","Bright Agency","website","real estate","location marketing","Custom site map and verified area copy organize location context. Map, context, proof and clear hierarchy; factual checking remains separate from design.",None,88,92,84,trust_level="HIGH"),
 ResearchDocument("https://www.luzcotheagency.com/case-studies-keswick-hall","luzcotheagency.com","agency_case_study","Luzco Creative Agency","website","luxury hospitality","premium developer campaign","Editorial, minimal and typography-led hospitality communication uses generous space, calm imagery and progressive section flow.",None,88,78,86,trust_level="HIGH"),
]

if __name__=="__main__":
 objective=ResearchObjective("validate_trend",["luxury real estate hero","real estate carousel","location marketing","unit layout presentation","premium developer campaign"],platforms=["instagram_feed","instagram_carousel","instagram_story","facebook"],industries=["real estate","luxury hospitality"],limit=12)
 path=CreativeResearchEngine(PROJECT_ROOT).run(objective,SOURCES)
 print(path)
