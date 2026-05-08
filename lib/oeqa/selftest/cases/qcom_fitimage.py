#
# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
#
# SPDX-License-Identifier: BSD-3-Clause-Clear
#
# Test cases for the QCOM DTB-only FIT image generation.
#
# These tests validate that QcomItsNodeRoot (used by dtb-fit-image.bbclass)
# produces correct ITS files so the UEFI firmware can parse them and select
# the right device tree at runtime.
#

import os
import re
import shutil
import logging

from oeqa.selftest.case import OESelftestTestCase
from oeqa.utils.commands import runCmd, bitbake, get_bb_vars

class QcomFitImageTests(OESelftestTestCase):
    """Unit tests for the QCOM DTB-only FIT image generator.

    Each test instantiates QcomItsNodeRoot directly, replicates the
    overlay-group processing from dtb-fit-image.bbclass, writes an ITS
    file, parses it back and asserts structural invariants that the UEFI
    firmware relies on.
    """

    # Valid metadata suffixes extracted from qcom-metadata.dts.
    # Used by test_compatible_string_format to cross-check compatible strings.
    METADATA_SUFFIXES = {
        # SoC
        "glymur", "hamoa", "purwa", "qcm6490", "qcs615", "qcs5430",
        "qcs6490", "qcs8275", "qcs8300", "qcs9075", "qcs9100", "sa8775p",
        # Board
        "adp", "atp", "cdp", "crd", "evk", "idp", "iot", "mtp", "qam", "qrd",
        # SoC version
        "socv1.0", "socv1.1", "socv2.0", "socv2.1",
        # Board revision
        "r1.0", "r1.1", "r2.0", "r2.1",
        # Peripheral subtype
        "subtype0", "subtype1", "subtype2", "subtype3", "subtype4",
        "subtype5", "subtype6", "subtype7", "subtype8", "subtype9",
        "subtype10",
        # Storage / memory / sku
        "emmc", "nand", "sdcard", "ufs",
        "256MB", "512MB", "1GB", "2GB", "3GB", "4GB",
        "sku0", "softsku0", "softsku1",
    }

    # Suffixes allowed by the metadata-check script's blacklist
    COMPAT_EXTENSIONS = {"camx", "el2kvm", "staging"}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _create_dummy_file(path, size=128):
        """Create a small random binary file (enough to satisfy mkimage)."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(os.urandom(size))

    def _get_test_dir(self):
        topdir = os.environ['BUILDDIR']
        d = os.path.join(topdir, 'qcom-fitimage-test', self._testMethodName)
        if os.path.exists(d):
            shutil.rmtree(d)
        os.makedirs(d, exist_ok=True)
        return d

    def _build_qcom_fitimage(self, kernel_devicetree, fit_dtb_compatible):
        """Replicate dtb-fit-image.bbclass logic and produce an ITS file.

        Args:
            kernel_devicetree: Space-separated DTB/DTBO filenames
                (the value of KERNEL_DEVICETREE).
            fit_dtb_compatible: Dict mapping DTB keys (with optional '+'
                for overlay combos) to compatible string(s)
                (the FIT_DTB_COMPATIBLE flags).

        Returns:
            (its_path, parsed) where *parsed* is the dict returned by
            ``_parse_its_file``.
        """
        # Lazy import: layer lib paths are only on sys.path after
        # _add_layer_libs() which runs *after* test module discovery.
        from qcom.dtb_only_fitimage import QcomItsNodeRoot

        test_dir = self._get_test_dir()
        dtb_dir = os.path.join(test_dir, 'dtbs')
        its_path = os.path.join(test_dir, 'qclinux-fit-image.its')

        root_node = QcomItsNodeRoot(
            "QCOM DTB-only FIT image for testing",
            "1",
            "conf-",
        )

        # ---- metadata DTB (always first) ----
        meta_path = os.path.join(dtb_dir, 'qcom-metadata.dtb')
        self._create_dummy_file(meta_path)
        root_node.fitimage_emit_section_dtb(
            "qcom-metadata.dtb", meta_path,
            compatible_str=None, dtb_type="qcom_metadata")

        # ---- replicate bbclass overlay-group parsing ----
        files_set = {os.path.basename(x)
                     for x in kernel_devicetree.split()}
        dtb_keys_list = {os.path.splitext(f)[0].replace(',', '_')
                         for f in files_set}

        overlay_groups = {}
        overlay_compats = {}
        for key, compat_val in fit_dtb_compatible.items():
            if '+' not in key:
                continue
            parts = [os.path.basename(p) for p in key.split('+')]
            if not parts:
                continue
            if not all(dtb in dtb_keys_list for dtb in parts):
                continue
            base = parts[0] + ".dtb"
            overlays = [ovl + ".dtbo" for ovl in parts[1:]]
            overlay_groups.setdefault(base, []).append(overlays)
            overlay_compats[key] = compat_val

        # ---- emit image nodes (sorted for deterministic output) ----
        for fname in sorted(files_set):
            fpath = os.path.join(dtb_dir, fname)
            self._create_dummy_file(fpath)
            dtb_id = fname.replace(',', '_')
            compatible = ""
            if fname.endswith(".dtb"):
                dtb_key = os.path.splitext(dtb_id)[0]
                compatible = fit_dtb_compatible.get(dtb_key, "")
            root_node.fitimage_emit_section_dtb(
                dtb_id, fpath,
                compatible_str=compatible, dtb_type="flat_dt")

        # ---- emit configuration nodes ----
        root_node.fitimage_emit_section_qcomconfig(
            overlay_groups, overlay_compats)

        root_node.write_its_file(its_path)
        parsed = self._parse_its_file(its_path)
        return its_path, parsed

    # ------------------------------------------------------------------
    # ITS parser
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_its_file(its_path):
        """Parse an ITS file into ``{images: {…}, configurations: {…}}``.

        Only properties of depth-3 nodes (direct children of ``images``
        or ``configurations``) are captured.
        """
        images = {}
        configs = {}
        path = []
        props = {}

        with open(its_path) as f:
            for line in f:
                s = line.strip()
                if not s or s == '/dts-v1/;':
                    continue
                if s.endswith('{'):
                    name = s[:-1].strip()
                    path.append(name)
                    if len(path) >= 3:
                        props = {}
                elif s == '};':
                    if len(path) == 3:
                        parent, node = path[1], path[2]
                        if parent == 'images':
                            images[node] = dict(props)
                        elif parent == 'configurations':
                            configs[node] = dict(props)
                    if path:
                        path.pop()
                elif '=' in s and s.endswith(';') and len(path) >= 3:
                    key, _, rest = s.partition('=')
                    key = key.strip()
                    val = rest.strip().rstrip(';').strip()
                    if val.startswith('/incbin/'):
                        props[key] = val
                    elif val.startswith('<') and val.endswith('>'):
                        props[key] = val
                    elif '", "' in val:
                        props[key] = re.findall(r'"([^"]*)"', val)
                    elif val.startswith('"') and val.endswith('"'):
                        props[key] = val[1:-1]
                    else:
                        props[key] = val

        return {'images': images, 'configurations': configs}

    # ------------------------------------------------------------------
    # Assertion helpers
    # ------------------------------------------------------------------

    def _get_config_compats(self, parsed):
        """Return the list of compatible strings across all configs."""
        return [p['compatible']
                for p in parsed['configurations'].values()
                if 'compatible' in p]

    def _assert_fdt_linkage(self, parsed):
        """Every ``fdt`` ref in every config must name an existing image."""
        img_names = set(parsed['images'].keys())
        for cname, cprops in parsed['configurations'].items():
            fdt = cprops.get('fdt')
            self.assertIsNotNone(fdt,
                f"Config {cname} has no 'fdt' property")
            refs = fdt if isinstance(fdt, list) else [fdt]
            for ref in refs:
                self.assertIn(ref, img_names,
                    f"Config {cname}: fdt '{ref}' not found in images")

    def _assert_metadata_excluded_from_configs(self, parsed):
        """qcom-metadata must never appear in any configuration node."""
        for cname, cprops in parsed['configurations'].items():
            fdt = cprops.get('fdt', '')
            refs = fdt if isinstance(fdt, list) else [fdt]
            for ref in refs:
                self.assertNotEqual(ref, 'fdt-qcom-metadata.dtb',
                    f"Config {cname} references metadata DTB")

    # ==================================================================
    # Test cases
    # ==================================================================

    def test_single_dtb_single_compat(self):
        """Single DTB with one compatible string."""
        _, p = self._build_qcom_fitimage(
            "myboard.dtb",
            {"myboard": "qcom,myboard-idp"})

        # Images
        self.assertIn('fdt-qcom-metadata.dtb', p['images'])
        self.assertEqual(
            p['images']['fdt-qcom-metadata.dtb']['type'], 'qcom_metadata')
        self.assertIn('fdt-myboard.dtb', p['images'])
        self.assertEqual(
            p['images']['fdt-myboard.dtb']['type'], 'flat_dt')

        # Exactly one config
        self.assertEqual(len(p['configurations']), 1)
        conf = p['configurations']['conf-1']
        self.assertEqual(conf['compatible'], 'qcom,myboard-idp')
        self.assertEqual(conf['fdt'], 'fdt-myboard.dtb')

        self._assert_fdt_linkage(p)
        self._assert_metadata_excluded_from_configs(p)

    def test_single_dtb_multi_compat(self):
        """Single DTB with multiple compatibles -> one config per compat."""
        _, p = self._build_qcom_fitimage(
            "qcs6490-rb3gen2.dtb",
            {"qcs6490-rb3gen2": "qcom,qcs5430-iot qcom,qcs6490-iot"})

        self.assertEqual(len(p['images']), 2)   # metadata + 1 DTB
        self.assertEqual(len(p['configurations']), 2)

        compats = self._get_config_compats(p)
        self.assertIn('qcom,qcs5430-iot', compats)
        self.assertIn('qcom,qcs6490-iot', compats)

        # Both configs reference the same DTB
        for conf in p['configurations'].values():
            self.assertEqual(conf['fdt'], 'fdt-qcs6490-rb3gen2.dtb')

        self._assert_fdt_linkage(p)
        self._assert_metadata_excluded_from_configs(p)

    def test_dtb_with_single_overlay(self):
        """Base DTB + overlay -> base config + overlay config with fdt list."""
        _, p = self._build_qcom_fitimage(
            "qcs6490-rb3gen2.dtb qcs6490-rb3gen2-vision-mezzanine.dtbo",
            {
                "qcs6490-rb3gen2": "qcom,qcs6490-iot",
                "qcs6490-rb3gen2+qcs6490-rb3gen2-vision-mezzanine": "qcom,qcs6490-iot-subtype2",
            })

        self.assertEqual(len(p['images']), 3)
        self.assertIn('fdt-qcs6490-rb3gen2-vision-mezzanine.dtbo', p['images'])

        self.assertEqual(len(p['configurations']), 2)

        base_found = ovl_found = False
        for conf in p['configurations'].values():
            if conf['compatible'] == 'qcom,qcs6490-iot':
                self.assertEqual(conf['fdt'], 'fdt-qcs6490-rb3gen2.dtb')
                base_found = True
            elif conf['compatible'] == 'qcom,qcs6490-iot-subtype2':
                self.assertIsInstance(conf['fdt'], list)
                self.assertEqual(
                    conf['fdt'],
                    ['fdt-qcs6490-rb3gen2.dtb', 'fdt-qcs6490-rb3gen2-vision-mezzanine.dtbo'])
                ovl_found = True
        self.assertTrue(base_found, "Missing base config")
        self.assertTrue(ovl_found, "Missing overlay config")

        self._assert_fdt_linkage(p)
        self._assert_metadata_excluded_from_configs(p)

    def test_dtb_with_multiple_overlays(self):
        """Base DTB + multiple stacked overlays."""
        _, p = self._build_qcom_fitimage(
            "lemans-evk.dtb lemans-evk-camx.dtbo "
            "lemans-el2.dtbo lemans-camx-el2.dtbo",
            {
                "lemans-evk": "qcom,qcs9075-iot",
                "lemans-evk+lemans-evk-camx+lemans-el2+lemans-camx-el2":
                    "qcom,qcs9075-iot-camx-el2kvm "
                    "qcom,qcs9075-socv2.0-iot-camx-el2kvm",
            })

        self.assertEqual(len(p['images']), 5)
        # 1 base + 2 overlay (one config per compatible string)
        self.assertEqual(len(p['configurations']), 3)

        expected_fdt_list = [
            'fdt-lemans-evk.dtb',
            'fdt-lemans-evk-camx.dtbo',
            'fdt-lemans-el2.dtbo',
            'fdt-lemans-camx-el2.dtbo',
        ]

        ovl_compats = []
        for conf in p['configurations'].values():
            compat = conf['compatible']
            if compat == 'qcom,qcs9075-iot':
                self.assertEqual(conf['fdt'], 'fdt-lemans-evk.dtb')
            else:
                ovl_compats.append(compat)
                self.assertIsInstance(conf['fdt'], list)
                self.assertEqual(conf['fdt'], expected_fdt_list)

        self.assertIn('qcom,qcs9075-iot-camx-el2kvm', ovl_compats)
        self.assertIn('qcom,qcs9075-socv2.0-iot-camx-el2kvm', ovl_compats)

        self._assert_fdt_linkage(p)
        self._assert_metadata_excluded_from_configs(p)

    def test_metadata_node_excluded_from_configs(self):
        """Metadata DTB appears as image (type=qcom_metadata) but never in configs."""
        _, p = self._build_qcom_fitimage(
            "simple.dtb",
            {"simple": "qcom,simple-evk"})

        meta = p['images'].get('fdt-qcom-metadata.dtb')
        self.assertIsNotNone(meta, "Metadata image node missing")
        self.assertEqual(meta['type'], 'qcom_metadata')

        self._assert_metadata_excluded_from_configs(p)

        for conf in p['configurations'].values():
            self.assertIn('compatible', conf)
            self.assertTrue(len(conf['compatible']) > 0)

    def test_overlay_filtering_by_kernel_devicetree(self):
        """Overlay combos whose DTBOs are absent from KERNEL_DEVICETREE are skipped."""
        _, p = self._build_qcom_fitimage(
            "base.dtb",            # overlay DTBO not listed
            {
                "base": "qcom,base-iot",
                "base+missing-overlay": "qcom,base-iot-subtype2",
            })

        # Only 1 config (base); overlay combo silently dropped
        self.assertEqual(len(p['configurations']), 1)
        conf = list(p['configurations'].values())[0]
        self.assertEqual(conf['compatible'], 'qcom,base-iot')
        self.assertEqual(conf['fdt'], 'fdt-base.dtb')
        self.assertEqual(len(p['images']), 2)   # metadata + base

    def test_fdt_linkage_validity(self):
        """Every fdt reference in every config matches an existing image."""
        _, p = self._build_qcom_fitimage(
            "board.dtb camx.dtbo el2.dtbo",
            {
                "board": "qcom,board-iot",
                "board+camx": "qcom,board-iot-subtype2",
                "board+camx+el2": "qcom,board-iot-el2kvm",
            })

        self._assert_fdt_linkage(p)

        # Ensure all DTBs are present as images
        self.assertIn('fdt-board.dtb', p['images'])
        self.assertIn('fdt-camx.dtbo', p['images'])
        self.assertIn('fdt-el2.dtbo', p['images'])

    def test_compatible_string_format(self):
        """Compatible strings use valid metadata suffixes (qcom,<soc>-<board>[-…])."""
        _, p = self._build_qcom_fitimage(
            "qcs6490-rb3gen2.dtb qcs6490-rb3gen2-vision-mezzanine.dtbo",
            {
                "qcs6490-rb3gen2":
                    "qcom,qcs6490-iot qcom,qcs5430-iot",
                "qcs6490-rb3gen2+qcs6490-rb3gen2-vision-mezzanine":
                    "qcom,qcs6490-iot-subtype2 qcom,qcs5430-iot-subtype2",
            })

        all_valid = self.METADATA_SUFFIXES | self.COMPAT_EXTENSIONS
        for cname, cprops in p['configurations'].items():
            compat = cprops.get('compatible', '')
            self.assertTrue(compat.startswith("qcom,"),
                f"Config {cname}: '{compat}' must start with 'qcom,'")
            for part in compat[len("qcom,"):].split('-'):
                if not part:
                    continue
                self.assertIn(part, all_valid,
                    f"Config {cname}: unknown suffix '{part}' in '{compat}'")

    def test_dtbo_no_standalone_config(self):
        """Overlay .dtbo files must never be the sole fdt in a config."""
        _, p = self._build_qcom_fitimage(
            "base.dtb overlay1.dtbo overlay2.dtbo",
            {
                "base": "qcom,base-iot",
                "base+overlay1": "qcom,base-iot-subtype1",
                "base+overlay2": "qcom,base-iot-subtype2",
            })

        for cname, cprops in p['configurations'].items():
            fdt = cprops.get('fdt', '')
            if isinstance(fdt, str):
                self.assertFalse(fdt.endswith('.dtbo'),
                    f"Config {cname}: standalone DTBO '{fdt}'")
            elif isinstance(fdt, list):
                self.assertTrue(fdt[0].endswith('.dtb'),
                    f"Config {cname}: first fdt '{fdt[0]}' must be a .dtb")

    def test_multiple_base_dtbs_with_overlays(self):
        """Multiple base DTBs each with their own overlay sets."""
        _, p = self._build_qcom_fitimage(
            "boardA.dtb boardA-cam.dtbo boardB.dtb boardB-cam.dtbo",
            {
                "boardA": "qcom,boardA-iot",
                "boardA+boardA-cam": "qcom,boardA-iot-subtype2",
                "boardB": "qcom,boardB-idp",
                "boardB+boardB-cam": "qcom,boardB-idp-subtype2",
            })

        self.assertEqual(len(p['images']), 5)  # metadata + 2×(base+ovl)
        self.assertEqual(len(p['configurations']), 4)

        compats = self._get_config_compats(p)
        for expected in ('qcom,boardA-iot', 'qcom,boardA-iot-subtype2',
                         'qcom,boardB-idp', 'qcom,boardB-idp-subtype2'):
            self.assertIn(expected, compats)

        # Overlay configs must not mix boards
        for conf in p['configurations'].values():
            compat, fdt = conf['compatible'], conf['fdt']
            if compat == 'qcom,boardA-iot-subtype2':
                self.assertIsInstance(fdt, list)
                self.assertIn('fdt-boardA.dtb', fdt)
                self.assertIn('fdt-boardA-cam.dtbo', fdt)
                self.assertNotIn('fdt-boardB.dtb', fdt)
            elif compat == 'qcom,boardB-idp-subtype2':
                self.assertIsInstance(fdt, list)
                self.assertIn('fdt-boardB.dtb', fdt)
                self.assertIn('fdt-boardB-cam.dtbo', fdt)
                self.assertNotIn('fdt-boardA.dtb', fdt)

        self._assert_fdt_linkage(p)
        self._assert_metadata_excluded_from_configs(p)

    def test_base_dtb_only_in_overlay(self):
        """Base DTB with no standalone compatible, used only via overlays."""
        _, p = self._build_qcom_fitimage(
            "base.dtb overlay.dtbo",
            {
                # No "base" key – the DTB is only referenced through overlays
                "base+overlay": "qcom,base-iot-subtype2",
            })

        # Only 1 config (the overlay combo), no base-only config
        self.assertEqual(len(p['configurations']), 1)
        conf = list(p['configurations'].values())[0]
        self.assertEqual(conf['compatible'], 'qcom,base-iot-subtype2')
        self.assertIsInstance(conf['fdt'], list)
        self.assertEqual(conf['fdt'],
                         ['fdt-base.dtb', 'fdt-overlay.dtbo'])

        self._assert_fdt_linkage(p)
        self._assert_metadata_excluded_from_configs(p)

    def test_mkimage_compile(self):
        """Compile the ITS with mkimage and verify with dumpimage."""
        its_path, p = self._build_qcom_fitimage(
            "testboard.dtb testboard-cam.dtbo",
            {
                "testboard": "qcom,testboard-iot",
                "testboard+testboard-cam": "qcom,testboard-iot-subtype2",
            })

        # Build u-boot-tools-native (mkimage/dumpimage) and dtc-native
        # (mkimage shells out to dtc to compile the ITS)
        bitbake("u-boot-tools-native dtc-native -c addto_recipe_sysroot")
        uboot_vars = get_bb_vars(
            ['RECIPE_SYSROOT_NATIVE', 'bindir'], 'u-boot-tools-native')
        uboot_bindir = os.path.join(
            uboot_vars['RECIPE_SYSROOT_NATIVE'], uboot_vars['bindir'])
        mkimage = os.path.join(uboot_bindir, 'mkimage')
        dumpimage = os.path.join(uboot_bindir, 'dumpimage')

        dtc_vars = get_bb_vars(
            ['RECIPE_SYSROOT_NATIVE', 'bindir'], 'dtc-native')
        dtc_bindir = os.path.join(
            dtc_vars['RECIPE_SYSROOT_NATIVE'], dtc_vars['bindir'])

        fit_path = its_path.replace('.its', '.bin')

        # Compile with external-data + 8-byte alignment (QCOM default)
        # dtc must be on PATH for mkimage to find it
        runCmd(f"{mkimage} -E -B 8 -f {its_path} {fit_path}",
               native_sysroot=dtc_vars['RECIPE_SYSROOT_NATIVE'])
        self.assertExists(fit_path, "mkimage did not produce a FIT image")

        # Verify structure with dumpimage
        result = runCmd(f"{dumpimage} -l {fit_path}")
        out = result.output
        self.assertIn("QCOM DTB-only FIT image for testing", out)

        # Check that image & configuration sections appear
        self.assertIn("fdt-testboard.dtb", out)
        self.assertIn("fdt-testboard-cam.dtbo", out)
        self.assertIn("fdt-qcom-metadata.dtb", out)

        # Verify at least the expected number of configurations
        conf_count = out.count("Configuration")
        self.assertGreaterEqual(conf_count, 2,
            "Expected at least 2 configuration entries in dumpimage output")


class QcomFitImageIntegrationTests(OESelftestTestCase):
    """Integration tests that build a real FIT image from the kernel recipe.

    These tests validate that dtb-fit-image.bbclass, fit-dtb-compatible.inc
    and QcomItsNodeRoot work together end-to-end to produce a FIT image that
    the UEFI firmware will be able to parse at boot.

    A real kernel build is triggered so that DTB files, the metadata blob and
    the FIT binary are all produced by the same tooling as in production.
    """

    # Cache build vars across helper calls within the same test run.
    _cached_bb_vars = None

    # Metadata DTS node names we extract once (class-level cache).
    _meta_nodes = None

    # Suffixes allowed by the metadata-check blacklist
    COMPAT_SKIP_PATTERNS = {"camx", "el2kvm", "staging"}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_bb_vars(self):
        """Retrieve bitbake variables needed by integration tests."""
        if self.__class__._cached_bb_vars is None:
            self.__class__._cached_bb_vars = get_bb_vars([
                'DEPLOY_DIR_IMAGE',
                'KERNEL_DEVICETREE',
                'MACHINE',
                'QCOM_DTB_DEFAULT',
                'FIT_CONF_PREFIX',
            ], 'virtual/kernel')
        return self.__class__._cached_bb_vars

    def _skip_unless_multi_dtb(self):
        """Skip the test unless the current MACHINE uses multi-dtb mode."""
        bb_vars = self._get_bb_vars()
        if bb_vars.get('QCOM_DTB_DEFAULT', '') != 'multi-dtb':
            self.skipTest(
                "MACHINE %s does not use multi-dtb FIT "
                "(QCOM_DTB_DEFAULT=%s)" %
                (bb_vars.get('MACHINE', '?'),
                 bb_vars.get('QCOM_DTB_DEFAULT', '?')))

    def _build_and_locate_fit(self):
        """Build virtual/kernel and return (its_path, fit_path, bb_vars).

        The build is triggered once; subsequent calls within the same
        oe-selftest invocation are essentially no-ops (sstate hit).
        """
        bb_vars = self._get_bb_vars()
        deploy_dir = bb_vars['DEPLOY_DIR_IMAGE']

        bitbake('virtual/kernel')

        its_path = os.path.join(deploy_dir, 'qclinux-fit-image.its')
        fit_path = os.path.join(deploy_dir, 'qclinuxfitImage')

        return its_path, fit_path, bb_vars

    @staticmethod
    def _parse_its_file(its_path):
        """Re-use the ITS parser from the unit-test class."""
        return QcomFitImageTests._parse_its_file(its_path)

    def _get_metadata_nodes(self, deploy_dir):
        """Extract valid node names from qcom-metadata.

        Decompiles the deployed qcom-metadata.dtb back to DTS using
        dtc-native, then parses node names.  This mirrors what
        check-fitimage-metadata.sh does.
        """
        if self.__class__._meta_nodes is not None:
            return self.__class__._meta_nodes

        meta_dtb = os.path.join(deploy_dir, 'qcom-metadata.dtb')
        if not os.path.exists(meta_dtb):
            return set()

        # Use dtc-native to decompile the .dtb to DTS text
        bitbake('dtc-native -c addto_recipe_sysroot')
        dtc_vars = get_bb_vars(
            ['RECIPE_SYSROOT_NATIVE', 'bindir'], 'dtc-native')
        dtc = os.path.join(
            dtc_vars['RECIPE_SYSROOT_NATIVE'], dtc_vars['bindir'], 'dtc')

        result = runCmd(f"{dtc} -I dtb -O dts {meta_dtb}")

        nodes = set()
        for line in result.output.splitlines():
            line = line.strip()
            if not line.endswith('{'):
                continue
            if line.startswith('&'):
                continue
            name = line.split()[0].rstrip(':').rstrip('{').strip()
            if name and name != '/' and name != 'description':
                nodes.add(name)

        self.__class__._meta_nodes = nodes
        return nodes

    def _setup_uboot_tools(self):
        """Build u-boot-tools-native and return the bindir."""
        bitbake('u-boot-tools-native -c addto_recipe_sysroot')
        uboot_vars = get_bb_vars(
            ['RECIPE_SYSROOT_NATIVE', 'bindir'], 'u-boot-tools-native')
        return os.path.join(
            uboot_vars['RECIPE_SYSROOT_NATIVE'], uboot_vars['bindir'])

    # ==================================================================
    # Integration tests
    # ==================================================================

    def test_fitimage_its_structure(self):
        """Build virtual/kernel and validate the generated ITS structure.

        Checks:
          - ITS and FIT files exist in DEPLOY_DIR_IMAGE
          - Every DTB from KERNEL_DEVICETREE has a corresponding image node
          - qcom-metadata.dtb image node exists with type=qcom_metadata
          - Every config has an fdt reference that exists in images
          - qcom-metadata never appears in any configuration
          - At least one configuration exists
        """
        self._skip_unless_multi_dtb()
        its_path, fit_path, bb_vars = self._build_and_locate_fit()

        self.assertExists(its_path,
            "ITS file not found in DEPLOY_DIR_IMAGE")
        self.assertExists(fit_path,
            "FIT binary not found in DEPLOY_DIR_IMAGE")

        parsed = self._parse_its_file(its_path)
        images = parsed['images']
        configs = parsed['configurations']

        # Metadata image node must exist and have correct type
        self.assertIn('fdt-qcom-metadata.dtb', images,
            "Missing qcom-metadata.dtb image node")
        self.assertEqual(images['fdt-qcom-metadata.dtb'].get('type'),
            'qcom_metadata',
            "Metadata image node has wrong type")

        # Every DTB from KERNEL_DEVICETREE must have an image node
        for dtb_path in bb_vars['KERNEL_DEVICETREE'].split():
            fname = os.path.basename(dtb_path).replace(',', '_')
            self.assertIn(f'fdt-{fname}', images,
                f"DTB '{fname}' from KERNEL_DEVICETREE missing in images")

        # Must have at least one configuration
        self.assertGreater(len(configs), 0,
            "No configuration nodes found in ITS")

        # FDT linkage: every fdt ref in configs must name an existing image
        for cname, cprops in configs.items():
            fdt = cprops.get('fdt')
            self.assertIsNotNone(fdt,
                f"Config {cname} has no 'fdt' property")
            refs = fdt if isinstance(fdt, list) else [fdt]
            for ref in refs:
                self.assertIn(ref, images,
                    f"Config {cname}: fdt '{ref}' not in images")

        # Metadata must never appear in any configuration
        for cname, cprops in configs.items():
            fdt = cprops.get('fdt', '')
            refs = fdt if isinstance(fdt, list) else [fdt]
            for ref in refs:
                self.assertNotEqual(ref, 'fdt-qcom-metadata.dtb',
                    f"Config {cname} references metadata DTB")

    def test_fitimage_dumpimage(self):
        """Verify the compiled FIT binary with dumpimage.

        Checks:
          - dumpimage can parse the FIT without errors
          - All DTBs from KERNEL_DEVICETREE appear in the dump
          - The metadata image node is listed
          - Configuration sections are present
        """
        self._skip_unless_multi_dtb()
        its_path, fit_path, bb_vars = self._build_and_locate_fit()
        self.assertExists(fit_path)

        bindir = self._setup_uboot_tools()
        dumpimage = os.path.join(bindir, 'dumpimage')

        result = runCmd(f"{dumpimage} -l {fit_path}")
        out = result.output

        # Metadata must appear
        self.assertIn('fdt-qcom-metadata.dtb', out,
            "Metadata node missing from dumpimage output")

        # All KERNEL_DEVICETREE entries must appear
        for dtb_path in bb_vars['KERNEL_DEVICETREE'].split():
            fname = os.path.basename(dtb_path).replace(',', '_')
            self.assertIn(f'fdt-{fname}', out,
                f"DTB '{fname}' missing from dumpimage output")

        # At least one configuration section must exist
        self.assertGreater(out.count('Configuration'), 0,
            "No configuration sections in dumpimage output")

    def test_fitimage_compatible_metadata_validation(self):
        """Cross-check compatible strings against qcom-metadata.dts.

        Every dash-separated suffix in each compatible string must
        either be a node name in the metadata DTS or be listed in
        the skip patterns (camx, el2kvm).

        This replicates the core check from check-fitimage-metadata.sh
        without requiring dtc.
        """
        self._skip_unless_multi_dtb()
        its_path, _, bb_vars = self._build_and_locate_fit()
        self.assertExists(its_path)

        parsed = self._parse_its_file(its_path)
        meta_nodes = self._get_metadata_nodes(bb_vars['DEPLOY_DIR_IMAGE'])

        # If we failed to load metadata nodes, fail loudly
        self.assertGreater(len(meta_nodes), 0,
            "Could not load any metadata nodes from qcom-metadata.dts")

        for cname, cprops in parsed['configurations'].items():
            compat = cprops.get('compatible', '')
            if not compat:
                continue

            self.assertTrue(compat.startswith('qcom,'),
                f"Config {cname}: compatible '{compat}' "
                f"must start with 'qcom,'")

            suffix_part = compat[len('qcom,'):]
            for part in suffix_part.split('-'):
                if not part:
                    continue
                if part in self.COMPAT_SKIP_PATTERNS:
                    continue
                self.assertIn(part, meta_nodes,
                    f"Config {cname}: suffix '{part}' from "
                    f"'{compat}' not found in metadata nodes "
                    f"(and not in skip list)")

    def test_fitimage_overlay_configs_fdt_list(self):
        """Overlay configurations must have an fdt list, not a single fdt.

        For any config whose fdt is a list, the first entry must be a
        base .dtb and the remaining entries must be .dtbo overlays.
        """
        self._skip_unless_multi_dtb()
        its_path, _, bb_vars = self._build_and_locate_fit()
        self.assertExists(its_path)

        parsed = self._parse_its_file(its_path)

        for cname, cprops in parsed['configurations'].items():
            fdt = cprops.get('fdt')
            if isinstance(fdt, list):
                self.assertTrue(fdt[0].endswith('.dtb'),
                    f"Config {cname}: first fdt '{fdt[0]}' in overlay "
                    f"list must be a .dtb")
                for ovl in fdt[1:]:
                    self.assertTrue(ovl.endswith('.dtbo'),
                        f"Config {cname}: overlay fdt '{ovl}' must "
                        f"be a .dtbo")
            elif isinstance(fdt, str):
                # Single-fdt configs must reference a .dtb, never a .dtbo
                self.assertTrue(fdt.endswith('.dtb'),
                    f"Config {cname}: standalone fdt '{fdt}' must "
                    f"be a .dtb, not a .dtbo")
