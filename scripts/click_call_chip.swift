#!/usr/bin/env swift
import AppKit
import CoreGraphics
import Foundation

let shot = URL(fileURLWithPath: "/tmp/rally-call-chip.png")
let capture = Process()
capture.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
capture.arguments = ["-x", shot.path]
try capture.run()
capture.waitUntilExit()
guard capture.terminationStatus == 0,
      let image = NSImage(contentsOf: shot),
      let tiff = image.tiffRepresentation,
      let rep = NSBitmapImageRep(data: tiff)
else {
    print("no-green-chip")
    exit(0)
}

let width = rep.pixelsWide
let height = rep.pixelsHigh
let yMax = max(1, min(height, Int(Double(height) * 0.22)))
let xMin = min(width - 1, Int(Double(width) * 0.78))
var sumX = 0
var sumY = 0
var count = 0
for y in 0..<yMax {
    for x in xMin..<width {
        guard let color = rep.colorAt(x: x, y: y) else { continue }
        let red = color.redComponent
        let green = color.greenComponent
        let blue = color.blueComponent
        if green >= 0.55 && red < 0.65 && blue < 0.65 && (green - red) >= 0.12 {
            sumX += x
            sumY += y
            count += 1
        }
    }
}
if count < 80 {
    print("no-green-chip")
    exit(0)
}

let scale = NSScreen.main?.backingScaleFactor ?? 2
let point = CGPoint(
    x: CGFloat(sumX / count) / scale,
    y: CGFloat(sumY / count) / scale)
let source = CGEventSource(stateID: .hidSystemState)
func click(_ point: CGPoint) {
    CGEvent(
        mouseEventSource: source, mouseType: .mouseMoved,
        mouseCursorPosition: point, mouseButton: .left)?.post(tap: .cghidEventTap)
    CGEvent(
        mouseEventSource: source, mouseType: .leftMouseDown,
        mouseCursorPosition: point, mouseButton: .left)?.post(tap: .cghidEventTap)
    CGEvent(
        mouseEventSource: source, mouseType: .leftMouseUp,
        mouseCursorPosition: point, mouseButton: .left)?.post(tap: .cghidEventTap)
}
click(point)
print("chip-click:\(Int(point.x)),\(Int(point.y))")
