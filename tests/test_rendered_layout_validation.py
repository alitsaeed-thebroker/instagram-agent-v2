"""Regressions for clipping and logo overlap missed by rectangle-only QA."""
from copy import deepcopy
import unittest
import hashlib
import tests.test_visual_art_director as fixtures
from src.creative.visual_direction import VisualArtDirector, validate_visual_direction_contract
from src.branding.composer import BrandComposer
from src.utils.text_layout import validate_text_layout
from src.publication import validate_public_copy

class RenderedLayoutTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.VisualArtDirectorTests();self.fixture.setUp()
        self.package=self.fixture.package()
        self.contract=VisualArtDirector().direct(self.package).contract
    def tearDown(self):self.fixture.tearDown()
    def test_long_project_identity_wraps_without_changing_copy(self):
        self.package['project_identity']['canonical_project_name']='VELORIA BY SHAHAN CO'
        contract=VisualArtDirector().direct(self.package).contract
        self.assertIsNotNone(contract);self.assertFalse(validate_text_layout(contract))
        self.assertEqual(' '.join(contract['project_identity']['render_text'].split()),'VELORIA BY SHAHAN CO')
    def test_glyph_overflow_is_rejected_even_with_in_bounds_rectangle(self):
        item=self.contract['headline'];item.update(text='W'*200,render_text='W'*200)
        self.assertTrue(any('glyphs overflow' in error for error in validate_visual_direction_contract(self.contract)))
        with self.assertRaises(ValueError):BrandComposer('p1',self.fixture.root).execute_visual_direction(self.contract)
    def test_logo_clear_space_cannot_cover_project_title(self):
        logo=self.contract['brand_logo'];title=self.contract['project_identity']
        title.update(x=logo['x'],y=logo['y'],width=logo['width'],height=logo['height'])
        self.assertTrue(any('overlaps brand_logo' in error for error in validate_visual_direction_contract(self.contract)))
    def test_rendered_copy_cannot_substitute_project_identity(self):
        self.contract['project_identity']['render_text']='Different project'
        self.assertTrue(any('changes approved copy' in error for error in validate_visual_direction_contract(self.contract)))
    def test_internal_funnel_labels_fail_public_copy_validation(self):
        for headline in ('Building: Consideration','Mixed Use Building Complex: Conversion','Building: Awareness'):
            self.assertTrue(validate_public_copy({'headline':headline}))
    def test_renderer_executes_all_approved_wrapped_text(self):
        self.package['project_identity']['canonical_project_name']='VELORIA BY SHAHAN CO'
        contract=VisualArtDirector().direct(self.package).contract
        contract['provenance'].update(source_image_hash=hashlib.sha256(self.fixture.image.read_bytes()).hexdigest(),logo_hash=hashlib.sha256(self.fixture.logo.read_bytes()).hexdigest())
        self.assertFalse(validate_visual_direction_contract(contract))
        output=BrandComposer('p1',self.fixture.root).execute_visual_direction(contract)
        self.assertTrue(output.is_file())
