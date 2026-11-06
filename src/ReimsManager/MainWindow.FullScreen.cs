using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Shell;
using System.Windows.Threading;

namespace ReimsManager;

public partial class MainWindow
{
    private bool fullScreen;
    private Window? fullScreenToolbar;
    private readonly DispatcherTimer fullScreenTimer = new(DispatcherPriority.Normal) { Interval = TimeSpan.FromMilliseconds(100) };
    private readonly Stopwatch topEdgeHover = new();
    private long fullScreenTicks, fullScreenTopSamples, fullScreenLongestDwell, fullScreenToolbarShows;
    private string fullScreenHoverState = "windowed";
    private Rect windowedBounds;
    private WindowState windowedState;
    private ResizeMode windowedResize;
    private WindowStyle windowedStyle;
    private WindowChrome? windowedChrome;
    private double windowedMinWidth, windowedMinHeight;
    private GridLength windowedTitleHeight;
    private Grid? sessionCommandParent;
    private int sessionCommandIndex;
    private FullScreenRect fullScreenBounds;

    private void ToggleFullScreen(object sender, RoutedEventArgs e)
    {
        if (fullScreen) { ExitFullScreen(); return; }
        if (IsUiBusy || !RequireAction("Console") || !TryCloseSettings()) return;
        DockConsole(sender, e);
        if (!ConsoleView.Attached) { ShowError(UiText.T("VM の画面に接続してから全画面表示にしてください。")); return; }
        windowedBounds = RestoreBounds;
        windowedState = WindowState;
        windowedStyle = WindowStyle;
        windowedResize = ResizeMode;
        windowedMinWidth = MinWidth; windowedMinHeight = MinHeight;
        windowedChrome = WindowChrome.GetWindowChrome(this);
        windowedTitleHeight = AppLayout.RowDefinitions[0].Height;
        sessionCommandParent = (Grid)SessionCommands.Parent;
        sessionCommandIndex = sessionCommandParent.Children.IndexOf(SessionCommands);
        fullScreen = true;
        fullScreenTicks = fullScreenTopSamples = fullScreenLongestDwell = fullScreenToolbarShows = 0;
        fullScreenHoverState = "waiting";
        try {
            WindowChrome.SetWindowChrome(this, null);
            MinWidth = MinHeight = 0;
            WindowState = WindowState.Normal;
            WindowStyle = WindowStyle.None;
            ResizeMode = ResizeMode.NoResize;
            ChromeRoot.Margin = new Thickness(0);
            AppLayout.RowDefinitions[0].Height = new GridLength(0);
            sessionCommandParent.Children.Remove(SessionCommands);
            var commands = new ScrollViewer { Content = SessionCommands, HorizontalScrollBarVisibility = ScrollBarVisibility.Auto, VerticalScrollBarVisibility = ScrollBarVisibility.Disabled };
            var surface = new Border { Child = commands, BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(0, 0, 8, 8) };
            surface.SetResourceReference(Border.BackgroundProperty, "CardBackground");
            surface.SetResourceReference(Border.BorderBrushProperty, "CardBorderBrush");
            fullScreenToolbar = new Window {
                Owner = this, Content = surface, WindowStyle = WindowStyle.None,
                ResizeMode = ResizeMode.NoResize, ShowInTaskbar = false, ShowActivated = false,
                SizeToContent = SizeToContent.WidthAndHeight, FontFamily = FontFamily, FontSize = FontSize,
                Left = Left, Top = Top, Title = "Reims Manager"
            };
            fullScreenToolbar.PreviewKeyDown += (_, key) => {
                if (key.Key is System.Windows.Input.Key.Escape or System.Windows.Input.Key.F11) { key.Handled = true; ExitFullScreen(); }
            };
            ApplyFullScreenBounds();
            fullScreenTimer.Tick += FullScreenTick;
            fullScreenTimer.Start();
            UpdatePowerControls();
        } catch (Exception error) {
            ExitFullScreen();
            ShowError(error.Message);
        }
    }

    private void ExitFullScreen(bool refresh = true)
    {
        if (!fullScreen) return;
        fullScreen = false;
        fullScreenTimer.Stop(); fullScreenTimer.Tick -= FullScreenTick;
        topEdgeHover.Reset();
        fullScreenHoverState = "windowed";
        if (fullScreenToolbar is { } toolbar) {
            if (toolbar.Content is Border { Child: ScrollViewer commands } surface) { commands.Content = null; surface.Child = null; }
            toolbar.Content = null;
            toolbar.Close();
            fullScreenToolbar = null;
        }
        if (SessionCommands.Parent is null && sessionCommandParent is not null)
            sessionCommandParent.Children.Insert(sessionCommandIndex, SessionCommands);
        AppLayout.RowDefinitions[0].Height = windowedTitleHeight;
        WindowStyle = windowedStyle; ResizeMode = windowedResize;
        WindowChrome.SetWindowChrome(this, windowedChrome);
        WindowState = WindowState.Normal;
        MinWidth = windowedMinWidth; MinHeight = windowedMinHeight;
        if (!windowedBounds.IsEmpty) {
            Left = windowedBounds.Left; Top = windowedBounds.Top;
            Width = windowedBounds.Width; Height = windowedBounds.Height;
        }
        WindowState = windowedState;
        if (refresh) UpdatePowerControls();
    }

    private nint MainHandle => new WindowInteropHelper(this).Handle;

    private void ApplyFullScreenBounds()
    {
        var monitor = new FullScreenMonitor { Size = Marshal.SizeOf<FullScreenMonitor>() };
        if (!GetFullScreenMonitorInfo(MonitorFromFullScreenWindow(MainHandle, 2), ref monitor))
            throw new Win32Exception(Marshal.GetLastWin32Error());
        fullScreenBounds = monitor.Bounds;
        if (fullScreenToolbar is not null)
            fullScreenToolbar.MaxWidth = Math.Max(1, (monitor.Bounds.Right - monitor.Bounds.Left - 16) / VisualTreeHelper.GetDpi(this).DpiScaleX);
        if (!PositionFullScreenWindow(MainHandle, 0, monitor.Bounds.Left, monitor.Bounds.Top,
            monitor.Bounds.Right - monitor.Bounds.Left, monitor.Bounds.Bottom - monitor.Bounds.Top,
            0x0010 | 0x0004 | 0x0200)) throw new Win32Exception(Marshal.GetLastWin32Error());
    }

    private void FullScreenTick(object? sender, EventArgs e)
    {
        if (!fullScreen || fullScreenToolbar is null) return;
        fullScreenTicks++;
        if (!FullScreenWindowEnabled(MainHandle) || WindowState == WindowState.Minimized || !ConsoleView.Attached) {
            SessionPowerButton.ContextMenu.IsOpen = SessionCursorMenuButton.ContextMenu.IsOpen = false;
            fullScreenToolbar.Hide(); topEdgeHover.Reset(); fullScreenHoverState = "unavailable"; return;
        }
        var monitor = new FullScreenMonitor { Size = Marshal.SizeOf<FullScreenMonitor>() };
        if (GetFullScreenMonitorInfo(MonitorFromFullScreenWindow(MainHandle, 2), ref monitor) &&
            (monitor.Bounds.Left != fullScreenBounds.Left || monitor.Bounds.Top != fullScreenBounds.Top ||
             monitor.Bounds.Right != fullScreenBounds.Right || monitor.Bounds.Bottom != fullScreenBounds.Bottom)) {
            fullScreenToolbar.Hide(); topEdgeHover.Reset();
            try { ApplyFullScreenBounds(); }
            catch (Win32Exception error) { ShowError(error.Message); }
            return;
        }
        if (!FullScreenCursor(out var cursor)) { topEdgeHover.Reset(); fullScreenHoverState = "cursor-unavailable"; return; }
        bool menu = SessionPowerButton.ContextMenu.IsOpen || SessionCursorMenuButton.ContextMenu.IsOpen;
        // A foreign guest owns its input queue; pointer hit-testing must not require Manager focus.
        nint pointedWindow = FullScreenWindowAt(cursor);
        nint toolbar = new WindowInteropHelper(fullScreenToolbar).Handle;
        // WPF's owned toolbar can still be its own GA_ROOTOWNER; recognize its HWND directly.
        bool overToolbarWindow = toolbar != 0 && (pointedWindow == toolbar || FullScreenAncestor(pointedWindow, 2) == toolbar);
        bool ownedPointer = overToolbarWindow || pointedWindow == MainHandle || FullScreenAncestor(pointedWindow, 3) == MainHandle;
        if (!ownedPointer && !menu) {
            fullScreenToolbar.Hide(); topEdgeHover.Reset(); fullScreenHoverState = "outside-console"; return;
        }
        bool atTop = cursor.X >= fullScreenBounds.Left && cursor.X < fullScreenBounds.Right &&
            cursor.Y >= fullScreenBounds.Top && cursor.Y < fullScreenBounds.Top + 32 * VisualTreeHelper.GetDpi(this).DpiScaleY;
        if (fullScreenToolbar.IsVisible) {
            bool overToolbar = FullScreenWindowRect(toolbar, out var bounds) && cursor.X >= bounds.Left && cursor.X < bounds.Right &&
                cursor.Y >= bounds.Top && cursor.Y < bounds.Bottom + 6;
            if (!atTop && !overToolbar && !menu) { fullScreenToolbar.Hide(); topEdgeHover.Reset(); }
            return;
        }
        if (!atTop) { topEdgeHover.Reset(); fullScreenHoverState = "below-top-strip"; return; }
        if ((FullScreenMouseButton(1) & 0x8000) != 0 || (FullScreenMouseButton(2) & 0x8000) != 0 || (FullScreenMouseButton(4) & 0x8000) != 0) {
            topEdgeHover.Reset(); fullScreenHoverState = "dragging"; return;
        }
        fullScreenTopSamples++;
        if (!topEdgeHover.IsRunning) topEdgeHover.Start();
        fullScreenLongestDwell = Math.Max(fullScreenLongestDwell, topEdgeHover.ElapsedMilliseconds);
        fullScreenHoverState = "dwelling";
        if (topEdgeHover.Elapsed < TimeSpan.FromSeconds(3)) return;
        // A sibling owned window can cover the foreign SDL viewport without activating it.
        fullScreenToolbar.Show();
        fullScreenToolbarShows++;
        fullScreenHoverState = "shown";
        nint bar = new WindowInteropHelper(fullScreenToolbar).Handle;
        if (FullScreenWindowRect(bar, out var rect))
            PositionFullScreenWindow(bar, 0, fullScreenBounds.Left + (fullScreenBounds.Right - fullScreenBounds.Left - rect.Right + rect.Left) / 2,
                fullScreenBounds.Top, 0, 0, 0x0001 | 0x0010 | 0x0200);
    }

    [StructLayout(LayoutKind.Sequential)] private struct FullScreenPoint { public int X, Y; }
    [StructLayout(LayoutKind.Sequential)] private struct FullScreenRect { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] private struct FullScreenMonitor { public int Size; public FullScreenRect Bounds, Work; public uint Flags; }
    [DllImport("user32.dll", EntryPoint = "MonitorFromWindow")] private static extern nint MonitorFromFullScreenWindow(nint window, uint flags);
    [DllImport("user32.dll", EntryPoint = "GetMonitorInfoW", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool GetFullScreenMonitorInfo(nint monitor, ref FullScreenMonitor info);
    [DllImport("user32.dll", EntryPoint = "SetWindowPos", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool PositionFullScreenWindow(nint window, nint after, int x, int y, int width, int height, uint flags);
    [DllImport("user32.dll", EntryPoint = "GetPhysicalCursorPos")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool FullScreenCursor(out FullScreenPoint point);
    [DllImport("user32.dll", EntryPoint = "WindowFromPhysicalPoint")] private static extern nint FullScreenWindowAt(FullScreenPoint point);
    [DllImport("user32.dll", EntryPoint = "GetAsyncKeyState")] private static extern short FullScreenMouseButton(int key);
    [DllImport("user32.dll", EntryPoint = "GetAncestor")] private static extern nint FullScreenAncestor(nint window, uint flags);
    [DllImport("user32.dll", EntryPoint = "IsWindowEnabled")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool FullScreenWindowEnabled(nint window);
    [DllImport("user32.dll", EntryPoint = "GetWindowRect")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool FullScreenWindowRect(nint window, out FullScreenRect rect);
}
