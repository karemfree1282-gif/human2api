'use strict';
let invoiceContent='';
document.getElementById('invoice-form').addEventListener('submit',(event)=>{
  event.preventDefault();
  const customer=document.getElementById('customer-name').value.trim();
  const amount=Number(document.getElementById('invoice-amount').value);
  if(!customer || !Number.isFinite(amount) || amount<=0) return;
  document.getElementById('invoice-summary').textContent=`Invoice for ${customer}: $${amount.toFixed(2)}`;
  invoiceContent=`ACME INVOICE\nCustomer: ${customer}\nAmount: $${amount.toFixed(2)}\nDemo only - no payment requested.\n`;
  document.getElementById('invoice-result').hidden=false;
});
document.getElementById('download-invoice').addEventListener('click',()=>{
  const url=URL.createObjectURL(new Blob([invoiceContent],{type:'text/plain'}));
  const link=document.createElement('a');link.href=url;link.download='demo-invoice.txt';document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
