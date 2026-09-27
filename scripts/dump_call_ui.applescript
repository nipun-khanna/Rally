on dumpProcess(procName)
	set out to "PROCESS " & procName & linefeed
	tell application "System Events"
		if not (exists process procName) then
			return out & "  missing" & linefeed
		end if
		tell process procName
			try
				set winNames to name of windows
				set out to out & "  windows: " & (winNames as text) & linefeed
			on error err
				set out to out & "  windows err: " & err & linefeed
			end try
			try
				set wcount to count of windows
				repeat with i from 1 to wcount
					set out to out & "  window " & i & linefeed
					try
						set btnNames to name of buttons of window i
						set out to out & "    buttons: " & (btnNames as text) & linefeed
					on error err
						set out to out & "    buttons err: " & err & linefeed
					end try
					try
						set uiNames to name of UI elements of window i
						set out to out & "    ui: " & (uiNames as text) & linefeed
					on error err
						set out to out & "    ui err: " & err & linefeed
					end try
					try
						if (count of sheets of window i) > 0 then
							set sNames to name of buttons of sheet 1 of window i
							set out to out & "    sheet buttons: " & (sNames as text) & linefeed
						end if
					end try
				end repeat
			end try
		end tell
	end tell
	return out
end dumpProcess

set report to ""
repeat with n in {"Phone", "FaceTime", "iPhone Mirroring", "NotificationCenter", "Notification Center"}
	set report to report & dumpProcess(n as text)
end repeat
return report
