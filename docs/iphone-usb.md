# iPhone USB handoff

Select **WinUSB** as the VM's USB transfer mode, completely exit QEMU, and
start the VM again after changing that setting. Select the iPhone in the
USB list. The administrator prompt authorizes a temporary driver change
for that selected phone. Windows may require unplugging and reconnecting
the phone before the new driver becomes active.

The package uses an existing signed libusb-win32 driver and the released
libusbK user-mode library. It needs no purchased signing certificate,
test-signing mode, signature-enforcement change or WSL. The signed INF and
catalog remain unchanged. Other phones and USB devices are not selected by
a broad VID/PID capture filter.

Normal mode uses the Windows Apple service to confirm the selected phone's
UDID and ECID. Recovery and DFU use the ECID in its actual USB serial
descriptor. An unavailable, duplicate or mismatched identity refuses the
handoff. The supervisor follows that identity across mode changes and gives
QEMU the complete Windows instance ID. USB addresses and physical ports
do not authorize a different phone.

The iPhone path permits guest-requested USB resets after address assignment.
It retains QEMU's default virtual initial reset while the guest address is
zero: forwarding that reset to the already enumerated Windows device caused
a reset/close/reopen loop before the guest could enumerate it. The generic USB path's
reset policy is unchanged. Selecting the phone does not itself enter DFU,
restore firmware or erase its data; those operations belong to guest tools.

Disconnecting or ending the VM removes the owned QEMU device before
restoring its recorded Apple driver. If the phone is absent, restoration
remains pending until the corresponding instance returns. Protected driver
receipts remain outside the user-writable VM directory. A Windows reboot
or termination of the supervisor can interrupt recovery: open Manager and
use the USB disconnect operation to resume it. Do not delete a pending
receipt or treat a reboot request as verified restoration.

Only one iPhone profile per VM is supported. Remove old generic iPhone
registrations before using the new identity-based handoff.

## Validation

The candidate's normal-mode physical check selected configurations 1, 3
and 4, read each value back through a real `GET_CONFIGURATION`, and claimed
and released the relevant interfaces. Its descriptor and original
configuration were also verified. The exact original Apple driver, native
driver stack and ECID were confirmed again afterward.

The recovery/DFU identity paths have CPU fixtures using authored descriptors.
QEMU's exact-instance property has passed paused device realization with an
authored absent identity, and rejects a DLL without the extension API.
Physical recovery, DFU, guest-driven firmware restoration and a complete
Manager-to-guest USB session are still unqualified. This source pin is a
private candidate until those acceptance checks are recorded.
