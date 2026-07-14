import SwiftUI

@main
struct XingyuLyricsAlignerApp: App {
    @StateObject private var viewModel = DesktopJobViewModel()
    @StateObject private var environment = EnvironmentReadinessViewModel()

    var body: some Scene {
        WindowGroup("星语歌词对齐器") {
            ContentView(viewModel: viewModel, environment: environment)
                .frame(minWidth: 820, minHeight: 720)
                .onReceive(NotificationCenter.default.publisher(for: NSApplication.willTerminateNotification)) { _ in
                    viewModel.shutdown()
                    environment.shutdown()
                }
        }
        .windowResizability(.contentMinSize)
        .defaultSize(width: 900, height: 840)
        .commands { AboutCommands() }

        Window("关于星语歌词对齐器", id: "about") {
            AboutView()
        }
        .windowResizability(.contentSize)
    }
}

private struct AboutCommands: Commands {
    @Environment(\.openWindow) private var openWindow

    var body: some Commands {
        CommandGroup(replacing: .appInfo) {
            Button("关于星语歌词对齐器") { openWindow(id: "about") }
                .keyboardShortcut(",", modifiers: .command)
        }
    }
}
