SUMMARY = "Packages for the SHIKRA platform"

inherit packagegroup

PACKAGES = " \
    ${PN}-firmware \
    ${PN}-hexagon-dsp-binaries \
"

RRECOMMENDS:${PN}-firmware = " \
    linux-firmware-qcom-vpu \
"

RRECOMMENDS:${PN}-hexagon-dsp-binaries = " \
"
