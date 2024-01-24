param(
  [string]$hostNo
)

$password = Read-Host -Prompt "Enter your password"

$ScriptDirectory = $PSScriptRoot



& "D:\OneDrive - cbb software GmbH\RuifengZhang\Apps\Winscp\WinSCP-5.19.6-Portable\WinSCP.com" `
  /log="./WinSCP.log" /ini=nul `
  /command `
    "open scp://pi:$password@192.168.1.23/ -hostkey=* " `
    "lcd `"$ScriptDirectory`"" `
    "cd /home/pi/hcp" `
    "put *.py -transfer=binary"  `
	"put *.sh -transfer=binary"  `
    "exit"

$winscpResult = $LastExitCode
if ($winscpResult -eq 0)
{
  Write-Host "Success"
  Remove-item ".\WinSCP.log"
}
else
{
  Write-Host "Error"
}

exit $winscpResult
