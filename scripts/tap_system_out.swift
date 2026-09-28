#!/usr/bin/env swift
import CoreAudio
import Darwin
import Foundation

// Passive copy of the default-output mix (Phone far-end on Speakers).
// PCM16 mono goes to stdout; status lines go to stderr.

func errln(_ line: String) {
    if let data = (line + "\n").data(using: .utf8) {
        FileHandle.standardError.write(data)
    }
}

let aggUID = "rally.voice.systemtap"
var excludePids: [pid_t] = [getpid()]
var argv = Array(CommandLine.arguments.dropFirst())
var index = 0
while index < argv.count {
    if argv[index] == "--exclude-pid", index + 1 < argv.count, let pid = pid_t(argv[index + 1]) {
        excludePids.append(pid)
        index += 2
        continue
    }
    index += 1
}

func processObject(for pid: pid_t) -> AudioObjectID? {
    var address = AudioObjectPropertyAddress(
        mSelector: kAudioHardwarePropertyTranslatePIDToProcessObject,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain)
    var pidValue = pid
    var object = AudioObjectID(kAudioObjectUnknown)
    var size = UInt32(MemoryLayout<AudioObjectID>.size)
    let status = AudioObjectGetPropertyData(
        AudioObjectID(kAudioObjectSystemObject), &address,
        UInt32(MemoryLayout<pid_t>.size), &pidValue, &size, &object)
    guard status == noErr, object != kAudioObjectUnknown else { return nil }
    return object
}

typealias TCCPreflight = @convention(c) (CFString, CFDictionary?) -> Int
typealias TCCRequest = @convention(c) (CFString, CFDictionary?, @escaping (Bool) -> Void) -> Void

func tccSymbol<T>(_ name: String, as type: T.Type) -> T? {
    guard let handle = dlopen(
        "/System/Library/PrivateFrameworks/TCC.framework/Versions/A/TCC", RTLD_NOW),
          let symbol = dlsym(handle, name) else { return nil }
    return unsafeBitCast(symbol, to: T.self)
}

let tccService = "kTCCServiceAudioCapture" as CFString
if let preflight = tccSymbol("TCCAccessPreflight", as: TCCPreflight.self) {
    var status = preflight(tccService, nil)
    errln("@AUTH preflight=\(status)")
    if status != 0, let request = tccSymbol("TCCAccessRequest", as: TCCRequest.self) {
        let wait = DispatchSemaphore(value: 0)
        var granted = false
        request(tccService, nil) { ok in
            granted = ok
            wait.signal()
        }
        if wait.wait(timeout: .now() + 90) == .timedOut {
            errln("@AUTH prompt-timeout continuing")
        }
        status = preflight(tccService, nil)
        errln("@AUTH granted=\(granted) after=\(status)")
        if status == 1 {
            errln("@AUTH denied: enable System Audio Recording for Terminal/Cursor, then retry")
        }
    }
}

func deviceUID(_ id: AudioObjectID) -> String? {
    var address = AudioObjectPropertyAddress(
        mSelector: kAudioDevicePropertyDeviceUID,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain)
    var size = UInt32(MemoryLayout<CFString?>.size)
    var value: CFString?
    let err = withUnsafeMutablePointer(to: &value) {
        AudioObjectGetPropertyData(id, &address, 0, nil, &size, $0)
    }
    guard err == noErr else { return nil }
    return value as String?
}

func allDeviceIDs() -> [AudioDeviceID] {
    var address = AudioObjectPropertyAddress(
        mSelector: kAudioHardwarePropertyDevices,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain)
    var size: UInt32 = 0
    let system = AudioObjectID(kAudioObjectSystemObject)
    guard AudioObjectGetPropertyDataSize(system, &address, 0, nil, &size) == noErr else {
        return []
    }
    let count = Int(size) / MemoryLayout<AudioDeviceID>.size
    var ids = [AudioDeviceID](repeating: 0, count: count)
    guard AudioObjectGetPropertyData(system, &address, 0, nil, &size, &ids) == noErr else {
        return []
    }
    return ids
}

for id in allDeviceIDs() where deviceUID(id) == aggUID {
    AudioHardwareDestroyAggregateDevice(id)
}

let excludeObjects = excludePids.compactMap(processObject(for:))
let tapDesc = CATapDescription(stereoGlobalTapButExcludeProcesses: excludeObjects)
tapDesc.isPrivate = true
tapDesc.muteBehavior = CATapMuteBehavior.unmuted

var tapID = AudioObjectID(kAudioObjectUnknown)
let tapStatus = AudioHardwareCreateProcessTap(tapDesc, &tapID)
guard tapStatus == noErr, tapID != kAudioObjectUnknown else {
    errln("tap-failed \(tapStatus)")
    exit(4)
}

let aggDesc: [String: Any] = [
    kAudioAggregateDeviceNameKey as String: "Rally System Tap",
    kAudioAggregateDeviceUIDKey as String: aggUID,
    kAudioAggregateDeviceIsPrivateKey as String: true,
    kAudioAggregateDeviceIsStackedKey as String: false,
    kAudioAggregateDeviceTapAutoStartKey as String: true,
    kAudioAggregateDeviceTapListKey as String: [[
        kAudioSubTapUIDKey as String: tapDesc.uuid.uuidString,
        kAudioSubTapDriftCompensationKey as String: true,
    ]],
]

var aggID = AudioObjectID(kAudioObjectUnknown)
let aggStatus = AudioHardwareCreateAggregateDevice(aggDesc as CFDictionary, &aggID)
guard aggStatus == noErr, aggID != kAudioObjectUnknown else {
    errln("aggregate-failed \(aggStatus)")
    AudioHardwareDestroyProcessTap(tapID)
    exit(5)
}

func deviceIsAlive(_ id: AudioObjectID) -> Bool {
    var address = AudioObjectPropertyAddress(
        mSelector: kAudioDevicePropertyDeviceIsAlive,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain)
    var alive: UInt32 = 0
    var size = UInt32(MemoryLayout<UInt32>.size)
    AudioObjectGetPropertyData(id, &address, 0, nil, &size, &alive)
    return alive != 0
}

let deadline = Date().addingTimeInterval(2)
while !deviceIsAlive(aggID), Date() < deadline {
    Thread.sleep(forTimeInterval: 0.05)
}

var fmtAddr = AudioObjectPropertyAddress(
    mSelector: kAudioDevicePropertyStreamFormat,
    mScope: kAudioObjectPropertyScopeInput,
    mElement: 0)
var asbd = AudioStreamBasicDescription()
var asbdSize = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
let fmtStatus = AudioObjectGetPropertyData(aggID, &fmtAddr, 0, nil, &asbdSize, &asbd)
guard fmtStatus == noErr, asbd.mSampleRate > 0 else {
    errln("format-failed \(fmtStatus)")
    AudioHardwareDestroyAggregateDevice(aggID)
    AudioHardwareDestroyProcessTap(tapID)
    exit(6)
}

errln("@RATE \(Int(asbd.mSampleRate))")
errln("@INFO ch=\(asbd.mChannelsPerFrame) float=\((asbd.mFormatFlags & kAudioFormatFlagIsFloat) != 0)")

var alive = true
let stdout = FileHandle.standardOutput
var procID: AudioDeviceIOProcID?
let ioStatus = AudioDeviceCreateIOProcIDWithBlock(&procID, aggID, nil) {
    (_, inInputData, _, _, _) in
    guard alive else { return }
    let buffers = UnsafeMutableAudioBufferListPointer(
        UnsafeMutablePointer(mutating: inInputData))
    guard !buffers.isEmpty else { return }
    let first = buffers[0]
    let channels = max(1, Int(first.mNumberChannels))
    let frames = Int(first.mDataByteSize) / (MemoryLayout<Float>.size * channels)
    guard frames > 0, let base = first.mData else { return }
    var pcm = [Int16](repeating: 0, count: frames)
    if buffers.count > 1 {
        let nch = buffers.count
        for frame in 0..<frames {
            var mix: Float = 0
            for channel in 0..<nch {
                guard let data = buffers[channel].mData else { continue }
                mix += data.assumingMemoryBound(to: Float.self)[frame]
            }
            mix /= Float(nch)
            pcm[frame] = Int16(max(-32767.0, min(32767.0, mix * 32767.0)))
        }
    } else {
        let samples = base.assumingMemoryBound(to: Float.self)
        for frame in 0..<frames {
            var mix: Float = 0
            for channel in 0..<channels {
                mix += samples[frame * channels + channel]
            }
            mix /= Float(channels)
            pcm[frame] = Int16(max(-32767.0, min(32767.0, mix * 32767.0)))
        }
    }
    pcm.withUnsafeBytes { raw in
        _ = Darwin.write(STDOUT_FILENO, raw.baseAddress, raw.count)
    }
}

guard ioStatus == noErr, let proc = procID else {
    errln("ioproc-failed \(ioStatus)")
    AudioHardwareDestroyAggregateDevice(aggID)
    AudioHardwareDestroyProcessTap(tapID)
    exit(7)
}

func teardown() {
    alive = false
    AudioDeviceStop(aggID, proc)
    AudioDeviceDestroyIOProcID(aggID, proc)
    AudioHardwareDestroyAggregateDevice(aggID)
    AudioHardwareDestroyProcessTap(tapID)
}

let sigHandler: @convention(c) (Int32) -> Void = { _ in alive = false }
signal(SIGINT, sigHandler)
signal(SIGTERM, sigHandler)
signal(SIGPIPE, SIG_IGN)

let startStatus = AudioDeviceStart(aggID, proc)
guard startStatus == noErr else {
    errln("start-failed \(startStatus)")
    teardown()
    exit(8)
}

errln("@READY")
while alive {
    RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.25))
}
teardown()
