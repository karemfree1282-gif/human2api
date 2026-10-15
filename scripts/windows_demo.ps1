# Safe self-contained Windows UIA test window (no external app or account).
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$form = New-Object System.Windows.Forms.Form
$form.Text = 'Human2API Windows Demo'
$form.Name = 'h2aWindowsDemo'
$form.Width = 520
$form.Height = 260
$form.StartPosition = 'CenterScreen'
$label = New-Object System.Windows.Forms.Label
$label.Name = 'demoHeader'
$label.Text = 'Human2API Windows UI Automation Test'
$label.Left = 22; $label.Top = 15; $label.Width = 450
$form.Controls.Add($label)
$inputBox = New-Object System.Windows.Forms.TextBox
$inputBox.Name = 'demo_input'
$inputBox.AccessibleName = 'Demo Note'
$inputBox.Left = 22; $inputBox.Top = 52; $inputBox.Width = 450
$form.Controls.Add($inputBox)
$button = New-Object System.Windows.Forms.Button
$button.Name = 'demo_submit'
$button.AccessibleName = 'Save Demo Note'
$button.Text = 'Save Demo Note'
$button.Left = 22; $button.Top = 90; $button.Width = 180
$form.Controls.Add($button)
$result = New-Object System.Windows.Forms.Label
$result.Name = 'demo_result'
$result.AccessibleName = 'Demo Result'
$result.Text = 'Not saved yet'
$result.Left = 22; $result.Top = 138; $result.Width = 455; $result.Height = 48
$form.Controls.Add($result)
$button.Add_Click({ $result.Text = 'Saved: ' + $inputBox.Text })
[void] $form.ShowDialog()
$form.Dispose()
