# Spoolman B-r3 at 4743816: invalid, the host was asleep

The run started at 12:28 (-03). Its last recorded event is at 12:32:55 (a map model call, answered). macOS's power log
shows the machine asleep (lid closed, on battery) until 14:49:09; every process was frozen and the monotonic clock
that bounds jobs stood still, so no timeout fired. Stopped at 14:52 and kept at
`~/unbidden-lab/spoolman-runs/s10-v3-4743816-B-r3-hung`. Not a result of the product. Later runs are started under
`caffeinate -i` (idle sleep prevented; a closed lid still sleeps the machine, and would invalidate a run again).
