-- Microphone and Output both Use System Setting.
-- System input = BlackHole 2ch (Grok mouth). System output = Rally Headphones.
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
		click menu item 12 of menu "Video" of menu bar item "Video" of menu bar 1
		delay 0.35
		click menu bar item "Video" of menu bar 1
		delay 0.3
		click menu item 19 of menu "Video" of menu bar item "Video" of menu bar 1
		delay 0.3
		return "phone-io:system-in,system-out"
	end tell
end tell
