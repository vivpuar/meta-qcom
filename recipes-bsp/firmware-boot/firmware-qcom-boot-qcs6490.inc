DESCRIPTION = "QCOM NHLOS Firmware for Qualcomm Robotics RB3Gen2 platform"
LICENSE = "Proprietary"
LIC_FILES_CHKSUM = "file://Qualcomm-Technologies-Inc.-Proprietary;md5=58d50a3d36f27f1a1e6089308a49b403"

FW_ARTIFACTORY = "softwarecenter.qualcomm.com/download/software/chip/qualcomm_linux-spf-1-0/qualcomm-linux-spf-1-0_test_device_public"
FW_BUILD_ID = "r1.0_${PV}/qcm6490-le-1-0"
FW_BIN_PATH = "common/build/ufs/bin"
BOOTBINARIES = "QCM6490_bootbinaries"

SRC_URI = " \
    https://${FW_ARTIFACTORY}/${FW_BUILD_ID}/${FW_BIN_PATH}/${BOOTBINARIES}.zip;downloadfilename=${BOOTBINARIES}_r1.0_${PV}.zip;name=bootbinaries \
    https://artifacts.codelinaro.org/artifactory/codelinaro-le/Qualcomm_Linux/QCS6490/cdt/rb3gen2-core-kit.zip;downloadfilename=cdt-rb3gen2-core-kit_${PV}.zip;name=rb3gen2-core-kit \
    "
SRC_URI[rb3gen2-core-kit.sha256sum] = "0fe1c0b4050cf54203203812b2c1f0d9698823d8defc8b6516414a4e5e0c557e"

QCOM_BOOT_IMG_SUBDIR = "qcm6490"

include firmware-qcom-boot-common.inc
