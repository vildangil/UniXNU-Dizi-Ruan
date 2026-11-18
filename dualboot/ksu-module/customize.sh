# KernelSU/Magisk installer hook: the zip's permission bits are not kept, so make the bundled bootctl executable.
set_perm "$MODPATH/bootctl" 0 0 0755
set_perm "$MODPATH/action.sh" 0 0 0755
