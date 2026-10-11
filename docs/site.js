'use strict';
const copy = document.getElementById('copy-command');
if (copy) copy.addEventListener('click', async () => {
  const commands = 'git clone https://github.com/karemfree1282-gif/human2api.git\ncd human2api\npython -m pip install -e .\npython -m playwright install chromium\nh2a serve';
  try {await navigator.clipboard.writeText(commands);copy.textContent='Copied ✓';setTimeout(()=>{copy.textContent='Copy commands ↗';},1800);}
  catch (_) {copy.textContent='Select commands to copy';}
});
