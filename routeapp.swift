import Cocoa
import WebKit
import Foundation

let pyPath = "/Users/apple/.workbuddy/binaries/python/versions/3.13.12/bin/python3"
let projDir = "/Users/apple/Downloads/个人信息/我做的小玩具/三模型路由系统"
let urlStr = "http://127.0.0.1:8000"

var serverProcess: Process?

func checkAlive(_ completion: @escaping (Bool) -> Void) {
    guard let url = URL(string: urlStr + "/health") else { completion(false); return }
    var req = URLRequest(url: url)
    req.timeoutInterval = 2
    URLSession.shared.dataTask(with: req) { _, resp, _ in
        let ok = (resp as? HTTPURLResponse)?.statusCode == 200
        completion(ok)
    }.resume()
}

func waitAlive(timeout: Double) -> Bool {
    let deadline = Date().addingTimeInterval(timeout)
    while Date() < deadline {
        var ready = false
        let sem = DispatchSemaphore(value: 0)
        checkAlive { ready = $0; sem.signal() }
        _ = sem.wait(timeout: .now() + 2)
        if ready { return true }
        Thread.sleep(forTimeInterval: 0.4)
    }
    return false
}

func ensureServer() {
    var alive = false
    let sem = DispatchSemaphore(value: 0)
    checkAlive { alive = $0; sem.signal() }
    _ = sem.wait(timeout: .now() + 2)
    if alive { return }

    let task = Process()
    task.executableURL = URL(fileURLWithPath: pyPath)
    task.arguments = ["-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "8000"]
    task.currentDirectoryURL = URL(fileURLWithPath: projDir)
    let log = FileHandle(forWritingAtPath: projDir + "/server.log") ?? FileHandle.nullDevice
    task.standardOutput = log
    task.standardError = log
    do { try task.run(); serverProcess = task } catch { return }
    _ = waitAlive(timeout: 15)
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var webview: WKWebView!

    func applicationDidFinishLaunching(_ notification: Notification) {
        ensureServer()

        let config = WKWebViewConfiguration()
        webview = WKWebView(frame: NSRect(x: 0, y: 0, width: 1120, height: 820), configuration: config)

        // 清除 WKWebView 缓存，确保每次打开都是最新前端
        let dataStore = WKWebsiteDataStore.default()
        let types = WKWebsiteDataStore.allWebsiteDataTypes()
        dataStore.removeData(ofTypes: types, modifiedSince: Date.distantPast) {}

        var req = URLRequest(url: URL(string: urlStr)!)
        req.cachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        webview.load(req)

        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1120, height: 820),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered, defer: false)
        window.title = "三模型路由系统"
        window.contentView = webview
        window.minSize = NSSize(width: 760, height: 560)
        window.center()
        window.makeKeyAndOrderFront(nil)
        window.isReleasedWhenClosed = false
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        serverProcess?.terminate()
        return true
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
