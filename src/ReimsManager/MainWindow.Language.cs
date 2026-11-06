using System.Windows;
using System.Windows.Controls;

namespace ReimsManager;

public partial class MainWindow
{
    private bool changingLanguage;

    private void LanguageChanged(object sender, SelectionChangedEventArgs e)
    {
        if (changingLanguage || LanguageChoice?.SelectedItem is not ComboBoxItem { Tag: string language } || settings is null) return;
        string previous = settings.Language;
        settings.Language = language;
        if (!SavePreferences()) {
            settings.Language = previous;
            changingLanguage = true; LanguageChoice.SelectedValue = previous; changingLanguage = false;
            return;
        }
        UiText.SetLanguage(settings.Language);
        UpdatePowerControls();
        UpdateLibraryView();
        UsbDevices.Items.Refresh();
        Uplink.Items.Refresh(); Physical.Items.Refresh();
    }
}
