import Foundation
import Speech
import AVFoundation

// The --authorize flag is an explicit local user action. Never fall back to cloud speech.
let args = Array(CommandLine.arguments.dropFirst())
let locale = Locale(identifier: "zh-CN")
guard let recognizer = SFSpeechRecognizer(locale: locale) else {
    FileHandle.standardError.write(Data("speech_locale_unavailable\n".utf8)); exit(2)
}
if args == ["--check"] {
    let result: [String: Any] = ["on_device": recognizer.supportsOnDeviceRecognition,
                               "authorization": SFSpeechRecognizer.authorizationStatus().rawValue,
                               "locale": locale.identifier]
    FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: result)); exit(0)
}
func fail(_ code: String) -> Never {
    FileHandle.standardError.write(Data((code + "\n").utf8)); exit(2)
}
guard recognizer.supportsOnDeviceRecognition else { fail("on_device_model_unavailable") }
var authorization = SFSpeechRecognizer.authorizationStatus()
if authorization == .notDetermined && args.contains("--authorize") {
    var done = false
    SFSpeechRecognizer.requestAuthorization { value in
        DispatchQueue.main.async { authorization = value; done = true }
    }
    let deadline = Date().addingTimeInterval(60)
    while !done && Date() < deadline { RunLoop.current.run(until: Date().addingTimeInterval(0.05)) }
}
guard authorization == .authorized else { fail("speech_permission_required") }
let inputs = args.filter { $0 != "--authorize" }
guard inputs.count == 1 else { fail("one_audio_file_required") }
let url = URL(fileURLWithPath: inputs[0])
do {
    let audio = try AVAudioFile(forReading: url)
    let duration = Double(audio.length) / audio.fileFormat.sampleRate
    guard duration.isFinite && duration > 0 && duration <= 60 else { fail("audio_duration_must_be_1_to_60_seconds") }
    let request = SFSpeechURLRecognitionRequest(url: url)
    request.requiresOnDeviceRecognition = true
    request.shouldReportPartialResults = false
    recognizer.queue = OperationQueue.main
    var output: String? = nil
    var failure: String? = nil
    let task = recognizer.recognitionTask(with: request) { result, error in
        if let result = result, result.isFinal { output = result.bestTranscription.formattedString }
        if error != nil { failure = "speech_recognition_failed" }
    }
    let deadline = Date().addingTimeInterval(120)
    while output == nil && failure == nil && Date() < deadline {
        RunLoop.current.run(until: Date().addingTimeInterval(0.05))
    }
    task.cancel()
    if let failure = failure { fail(failure) }
    guard let text = output else { fail("speech_timeout") }
    guard !text.isEmpty else { fail("speech_empty") }
    FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: ["raw_text": String(text.prefix(24000)), "truncated": text.count > 24000, "processor": "apple_speech_ondevice"]))
} catch { fail("audio_unreadable") }
