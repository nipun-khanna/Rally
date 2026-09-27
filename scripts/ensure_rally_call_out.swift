#!/usr/bin/env swift
import CoreAudio
import Foundation

// Looks like headphones/speakers to Phone.app (master = built-in speakers)
// and copies the same stream into BlackHole 16ch for Grok to hear.
let name = "Rally Headphones"
let uid = "rally.headphones"
let speakers = "BuiltInSpeakerDevice"
let hole = "BlackHole16ch_UID"

var listAddr = AudioObjectPropertyAddress(
    mSelector: kAudioHardwarePropertyDevices,
    mScope: kAudioObjectPropertyScopeGlobal,
    mElement: kAudioObjectPropertyElementMain)
var dataSize: UInt32 = 0
AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject), &listAddr, 0, nil, &dataSize)
let count = Int(dataSize) / MemoryLayout<AudioDeviceID>.size
var ids = [AudioDeviceID](repeating: 0, count: count)
AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &listAddr, 0, nil, &dataSize, &ids)

func deviceName(_ id: AudioDeviceID) -> String {
    var addr = AudioObjectPropertyAddress(
        mSelector: kAudioObjectPropertyName,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain)
    var size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
    var cf: Unmanaged<CFString>?
    let err = withUnsafeMutablePointer(to: &cf) {
        AudioObjectGetPropertyData(id, &addr, 0, nil, &size, $0)
    }
    guard err == noErr, let cf else { return "" }
    return cf.takeUnretainedValue() as String
}

if ids.contains(where: { deviceName($0) == name }) {
    print("exists \(name)")
    exit(0)
}

let desc: [String: Any] = [
    kAudioAggregateDeviceNameKey as String: name,
    kAudioAggregateDeviceUIDKey as String: uid,
    kAudioAggregateDeviceIsStackedKey as String: 1,
    kAudioAggregateDeviceMasterSubDeviceKey as String: speakers,
    kAudioAggregateDeviceSubDeviceListKey as String: [
        [kAudioSubDeviceUIDKey as String: speakers],
        [kAudioSubDeviceUIDKey as String: hole],
    ],
]
var aggregate = AudioObjectID(0)
let status = AudioHardwareCreateAggregateDevice(desc as CFDictionary, &aggregate)
if status != noErr {
    fputs("create-failed \(status)\n", stderr)
    exit(1)
}
print("created \(name) id=\(aggregate)")
