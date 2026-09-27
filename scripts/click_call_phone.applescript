tell application "System Events"
	if exists process "Phone" then
		tell process "Phone"
			try
				set frontmost to true
			end try
			try
				click (first button of sheet 1 of window 1 whose name is "Call")
				return "phone-sheet-Call"
			end try
			try
				click (first button of window 1 whose name is "Call")
				return "phone-window-Call"
			end try
			try
				click button "Call" of window 1
				return "phone-button-Call"
			end try
		end tell
	end if
end tell
return "phone-miss"
