tell application "System Events"
	repeat with ncName in {"NotificationCenter", "Notification Center"}
		if exists process ncName then
			tell process ncName
				try
					click button "Call" of group 1 of UI element 1 of scroll area 1 of group 1 of window 1
					return "nc-sonoma-Call:" & (ncName as text)
				end try
				try
					click UI element "Call" of group 1 of UI element 1 of scroll area 1 of windows
					return "nc-ui-Call:" & (ncName as text)
				end try
				try
					click button "Call" of window 1
					return "nc-window-Call:" & (ncName as text)
				end try
				try
					click button "Call" of windows
					return "nc-windows-Call:" & (ncName as text)
				end try
			end tell
		end if
	end repeat
end tell
return "nc-miss"
