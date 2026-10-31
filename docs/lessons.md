# Lessons

## Group PowerShell boolean guards before indexing

PowerShell evaluates `-and` and `-or` at the same precedence, from left to
right. `empty -or active -and rows[0]` can therefore read `rows[0]` even when
`empty` is true. The iPhone supervisor hit this during the physical absence
between unplug and reconnect, stopped its session, and restored the driver.

Write `empty -or (active -and rows[0])` and exercise both initial absence
and an actual disappear/reappear interval. Advancing an arrival timestamp
while leaving the device present does not reproduce a physical reconnect.
