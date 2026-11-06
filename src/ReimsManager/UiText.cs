using System.ComponentModel;
using System.Globalization;
using System.Resources;
using System.Windows.Data;
using System.Windows.Markup;

namespace ReimsManager;

internal sealed class UiText : INotifyPropertyChanged
{
    private static readonly ResourceManager Resources = new("ReimsManager.Strings", typeof(UiText).Assembly);
    private static readonly CultureInfo SystemLanguage = CultureInfo.CurrentUICulture;
    internal static UiText Current { get; } = new();
    public string Language { get; private set; } = "auto";
    private CultureInfo culture = CultureInfo.GetCultureInfo(SystemLanguage.TwoLetterISOLanguageName == "ja" ? "ja" : "en");
    public event PropertyChangedEventHandler? PropertyChanged;

    internal static string T(string text) => Resources.GetString(text, Current.culture) ?? text;
    internal static string UsbLabel(string label)
    {
        int status = label.LastIndexOf('［');
        return status < 0 ? label : label[..status] + T(label[status..]);
    }
    internal static string Format(FormattableString text) => string.Format(CultureInfo.CurrentCulture, T(text.Format), text.GetArguments());
    internal static void SetLanguage(string language)
    {
        Current.Language = language is "ja" or "en" ? language : "auto";
        string selected = Current.Language == "auto" ? (SystemLanguage.TwoLetterISOLanguageName == "ja" ? "ja" : "en") : Current.Language;
        Current.culture = CultureInfo.GetCultureInfo(selected);
        CultureInfo.CurrentUICulture = Current.culture;
        Current.PropertyChanged?.Invoke(Current, new PropertyChangedEventArgs(nameof(Language)));
    }
}

[MarkupExtensionReturnType(typeof(string))]
public sealed class LocExtension : MarkupExtension, IValueConverter
{
    public LocExtension(string text) => Text = text;
    public string Text { get; }
    public override object ProvideValue(IServiceProvider serviceProvider) => new Binding(nameof(UiText.Language)) {
        Source = UiText.Current, Mode = BindingMode.OneWay, Converter = this
    }.ProvideValue(serviceProvider);
    public object Convert(object value, Type targetType, object parameter, CultureInfo culture) => UiText.T(Text);
    public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture) => throw new NotSupportedException();
}
