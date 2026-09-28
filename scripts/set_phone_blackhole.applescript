-- Microphone and Output both Use System Setting.
-- System input = BlackHole 2ch (Grok mouth). System output = Speakers
-- (far-end plays here; Core Audio tap copies that mix to Grok).
tell application "Phone" to activate
delay 0.4
tell application "System Events"
	if not (exists process "Phone") then
		return "phone-missing"
	end if
	tell process "Phone"
		set frontmost to true
		delay 0.2
		click menu bar item "Video" of menu bar 1
		delay 0.3
		set choices to every menu item of menu "Video" of menu bar item "Video" of menu bar 1 whose name is "Use System Setting"
		if (count of choices) is not 2 then error "Expected microphone and output system settings"
		click item 1 of choices
		delay 0.35
		click menu bar item "Video" of menu bar 1
		delay 0.3
		set choices to every menu item of menu "Video" of menu bar item "Video" of menu bar 1 whose name is "Use System Setting"
		if (count of choices) is not 2 then error "Expected microphone and output system settings"
		click item 2 of choices
		delay 0.3
		click menu bar item "Video" of menu bar 1
		delay 0.3
		set choices to every menu item of menu "Video" of menu bar item "Video" of menu bar 1 whose name is "Use System Setting"
		if (count of choices) is not 2 then error "Cannot verify Phone audio settings"
		repeat with choice in choices
			set mark to value of attribute "AXMenuItemMarkChar" of choice
			if mark is missing value or mark is "" then error "Phone audio setting was not selected"
		end repeat
		key code 53
		return "phone-io:system-in,system-out"
	end tell
end tell
