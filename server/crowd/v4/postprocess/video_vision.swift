import Foundation
import Vision

// JSONL local-image protocol. One process, bounded autorelease per sampled frame.
var count = 0
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["zh-Hans", "en-US"]
request.usesLanguageCorrection = true
while let line = readLine() {
    count += 1
    guard count <= 14400, line.utf8.count <= 4096 else { exit(2) }
    do {
        try autoreleasepool {
            let began = Date().timeIntervalSinceReferenceDate
            guard let value = try JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any],
                  let path = value["path"] as? String, let index = value["index"] as? Int else { exit(2) }
            try VNImageRequestHandler(url: URL(fileURLWithPath: path), options: [:]).perform([request])
            let observations = request.results ?? []
            var truncated = observations.count > 50
            let blocks: [[String: Any]] = observations.prefix(50).compactMap { observation in
                guard let candidate = observation.topCandidates(1).first else { return nil }
                if candidate.string.count > 500 { truncated = true }
                let box = observation.boundingBox
                return ["text": String(candidate.string.prefix(500)), "confidence": candidate.confidence,
                        "bbox": [box.minX, box.minY, box.width, box.height]]
            }
            let data = try JSONSerialization.data(withJSONObject: ["index": index, "blocks": blocks,
                "truncated": truncated,
                "native_seconds": Date().timeIntervalSinceReferenceDate - began], options: [.sortedKeys])
            FileHandle.standardOutput.write(data)
            FileHandle.standardOutput.write(Data("\n".utf8))
        }
    } catch {
        FileHandle.standardError.write(Data("video_vision_unavailable\n".utf8))
        exit(1)
    }
}
