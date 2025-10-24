# Configurations and variables for SM8850 SoC family.

SOC_FAMILY = "sm8850"
require conf/machine/include/qcom-base.inc
require conf/machine/include/qcom-common.inc

#QCOM_VFAT_SECTOR_SIZE = "512"
#require conf/machine/include/arm/armv8a/tune-cortexa53.inc

DEFAULTTUNE = "armv8-2a-crypto"
require conf/machine/include/arm/arch-armv8-2a.inc

MACHINE_ESSENTIAL_EXTRA_RRECOMMENDS += " \
    packagegroup-qcom-boot-essential \
"

MACHINE_EXTRA_RRECOMMENDS += " \
    packagegroup-qcom-boot-additional \
"
