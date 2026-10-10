document.addEventListener('DOMContentLoaded',()=>{
 const btn=document.getElementById('menuToggle');
 if(btn)btn.addEventListener('click',()=>document.getElementById('sidebar')?.classList.toggle('open'));
 document.querySelectorAll('[data-confirm]').forEach(form=>form.addEventListener('submit',e=>{if(!confirm(form.dataset.confirm))e.preventDefault()}));
 document.querySelectorAll('[data-table-filter]').forEach(input=>input.addEventListener('input',()=>{
   const table=document.getElementById(input.dataset.tableFilter);const query=input.value.trim().toLowerCase();
   if(table)table.querySelectorAll('tbody tr').forEach(tr=>{tr.hidden=!tr.textContent.toLowerCase().includes(query)})
 }));
 const files=document.getElementById('photos');if(files)files.addEventListener('change',()=>{
   if(files.files.length>3){alert('Select at most three images.');files.value='';return}
   for(const f of files.files){if(f.size>5*1024*1024){alert('Each image must be 5 MB or smaller.');files.value='';return}}
 });
 const newForm=document.getElementById('newComplaintForm');if(newForm)newForm.addEventListener('submit',()=>{
    const btn=document.getElementById('submitBtn');if(btn){btn.disabled=true;btn.textContent='Submitting...'}
 });
});
