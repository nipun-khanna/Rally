-- Proven on this Mac: Phone.app has no AX windows for the confirm sheet.
-- The Call control is UI element "Call" under NotificationCenter.
tell application "System Events"
	repeat with ncName in {"NotificationCenter", "Notification Center"}
		if exists process ncName then
			tell process ncName
				try
					click UI element "Call" of group 1 of UI element 1 of scroll area 1 of windows
					return "nc-ui-Call:" & (ncName as text)
				end try
				try
					click button "Call" of group 1 of UI element 1 of scroll area 1 of group 1 of window 1
					return "nc-sonoma-Call:" & (ncName as text)
				end try
				try
					click button "Call" of window 1
					return "nc-window-Call:" & (ncName as text)
				end try
			end tell
		end if
	end repeat
	repeat with appName in {"Phone", "FaceTime", "iPhone Mirroring"}
		if exists process appName then
			tell process appName
				try
					set frontmost to true
				end try
				try
					click (first button of sheet 1 of window 1 whose name is "Call")
					return "clicked-Call-sheet:" & (appName as text)
				end try
				try
					click (first button of window 1 whose name is "Call")
					return "clicked-Call-window:" & (appName as text)
				end try
			end tell
		end if
	end repeat
end tell
return "no-confirm-button"
