(function(){
var d=document,views=[].slice.call(d.querySelectorAll('[data-view]')),
    subs=views.filter(function(v){return v.dataset.view!=='home'}).map(function(v){return v.id});
function show(id){var sw=false;views.forEach(function(v){var on=id?v.id===id:v.dataset.view==='home';if(on!==v.classList.contains('on'))sw=true;v.classList.toggle('on',on)});return sw}
function langLinks(id){[].forEach.call(d.querySelectorAll('a[data-lang-base]'),function(a){var b=a.getAttribute('data-lang-base');if(b.charAt(0)!=='#')a.setAttribute('href',b+(id&&id!=='top'?'#'+id:''))})}
function route(id){
  if(typeof id!=='string')id=decodeURIComponent((location.hash||'').slice(1));
  langLinks(id);
  if(subs.indexOf(id)>-1){show(id);window.scrollTo({top:0,behavior:'instant'});var h=d.getElementById(id).querySelector('h1');if(h)h.focus({preventScroll:true});return}
  var sw=show(null),el=id&&id!=='top'?d.getElementById(id):null;
  if(el)requestAnimationFrame(function(){el.scrollIntoView({behavior:sw?'instant':'smooth'})});
  else window.scrollTo({top:0,behavior:sw?'instant':'smooth'});
}
d.addEventListener('click',function(e){
  if(e.defaultPrevented||e.button!==0||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;
  var a=e.target.closest&&e.target.closest('a[href^="#"]');if(!a)return;
  var id=a.getAttribute('href').slice(1);if(id&&!d.getElementById(id))return;
  e.preventDefault();try{if(location.hash!=='#'+id)history.pushState(null,'','#'+id)}catch(x){}
  route(id);
});
window.addEventListener('hashchange',function(){route()});
window.addEventListener('popstate',function(){route()});
route();
})();
