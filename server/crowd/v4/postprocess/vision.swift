import Foundation
import Vision

// Local files only. OCR confidence is recognition confidence, not factual accuracy.
guard CommandLine.arguments.count == 2 else { exit(2) }
do {
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["zh-Hans", "en-US"]
request.usesLanguageCorrection = true
try VNImageRequestHandler(url: URL(fileURLWithPath: CommandLine.arguments[1]), options: [:]).perform([request])
let observations = request.results ?? []
var truncated = observations.count > 200
let blocks: [[String: Any]] = observations.prefix(200).compactMap { observation in
    guard let candidate = observation.topCandidates(1).first else { return nil }
    if candidate.string.count > 2000 { truncated = true }
    let box = observation.boundingBox
    return ["text": String(candidate.string.prefix(2000)), "confidence": candidate.confidence,
            "bbox": [box.minX, box.minY, box.width, box.height],
            "semantic_type": "unclassified", "review_status": "unreviewed"]
}
let data = try JSONSerialization.data(withJSONObject: ["blocks": blocks, "truncated": truncated], options: [.sortedKeys])
FileHandle.standardOutput.write(data)

} catch {
    FileHandle.standardError.write(Data("vision_unavailable\n".utf8))
    exit(1)
}
