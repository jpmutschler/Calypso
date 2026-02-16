# Verify PLX_CHIP is set
ifndef PLX_CHIP
    $(error ERROR: Variable 'PLX_CHIP' not set ***)
endif

# Set PLX folder
ifndef PLX_DIR
    PLX_DIR=$(PLX_SDK_DIR)
endif

# Include PLX driver-specific makefile
ifneq ($(wildcard $(PLX_DIR)/Driver/Source.Plx9000/Chip/$(PLX_CHIP)),)
    include $(PLX_DIR)/Driver/Source.Plx9000/Makefile
else
    include $(PLX_DIR)/Driver/Source.Plx$(PLX_CHIP)/Makefile
endif

# Include PLX makefiles
include $(PLX_DIR)/Makefiles/MakeDriver.def

# Build driver
ifneq ($(KERNELRELEASE),)

    obj-m := $(ImageName).o

    $(ImageName)-objs := $(PLX_OBJECTS)

    # Bridge EXTRA_CFLAGS to ccflags-y for kernel 6.x+ kbuild compatibility.
    # EXTRA_CFLAGS was deprecated in 3.10 and the compat shim was removed in 6.x.
    ccflags-y += $(EXTRA_CFLAGS)

endif
