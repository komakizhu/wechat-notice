import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const dir = dirname(fileURLToPath(import.meta.url));
const C = { paper:'#f8f3e9', white:'#fffdf9', ink:'#243235', muted:'#566665', line:'#c9c3b7', blue:'#e5eff0', blueLine:'#72989b', green:'#e8f0e6', greenLine:'#779478', amber:'#f6ead3', amberLine:'#b28645' };
const esc = s => String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
const svg = content => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 440 900" role="img"><style>text{font-family:PingFang SC,Noto Sans SC,Microsoft YaHei,sans-serif;fill:${C.ink}}</style><rect width="440" height="900" fill="${C.paper}"/>${content}</svg>`;
const rect = (x,y,w,h,fill,stroke=C.line,r=12,sw=1.3) => `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${r}" fill="${fill}" stroke="${stroke}" stroke-width="${sw}"/>`;
const t = (x,y,value,size=14,weight=500,anchor='start',color=C.ink) => `<text x="${x}" y="${y}" text-anchor="${anchor}" font-size="${size}" font-weight="${weight}" fill="${color}">${esc(value)}</text>`;
const lines = (x,y,parts,size=13,weight=500,anchor='middle',lineH=18,color=C.ink) => parts.map((p,i)=>t(x,y+i*lineH,p,size,weight,anchor,color)).join('');
const path = (d,color=C.line,width=2,dash='') => `<path d="${d}" fill="none" stroke="${color}" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round" ${dash?`stroke-dasharray="${dash}"`:''}/>`;
const dot = (x,y,r,fill) => `<circle cx="${x}" cy="${y}" r="${r}" fill="${fill}"/>`;
const arrow = (x,y,dir,color) => { const p=dir==='right'?`${x-5},${y-4} ${x+3},${y} ${x-5},${y+4}`:dir==='left'?`${x+5},${y-4} ${x-3},${y} ${x+5},${y+4}`:`${x-4},${y-5} ${x},${y+3} ${x+4},${y-5}`; return `<polyline points="${p}" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>`; };
const card=(x,y,w,h,num,parts,tone='blue',font=13)=>{
  const bg=tone==='blue'?C.blue:C.green, edge=tone==='blue'?C.blueLine:C.greenLine;
  const centerY=y+h/2-(parts.length-1)*8+5;
  return rect(x,y,w,h,bg,edge,10)+dot(x+19,y+19,13,edge)+t(x+19,y+24,num,12,700,'middle',C.white)+lines(x+w/2+8,centerY,parts,font,600,'middle',17);
};
const header=(name)=>{
  let s=t(22,42,'中秋·国庆｜学生离校报备',22,700);
  s+=t(418,40,name,10,700,'end',C.muted);
  s+=rect(22,62,192,60,C.blue,C.blueLine)+t(38,86,'中秋  9月25—27日',15,700)+t(38,108,'3天',11,500,'start',C.muted);
  s+=rect(226,62,192,60,C.green,C.greenLine)+t(242,86,'国庆  10月1—7日',15,700)+t(242,108,'7天',11,500,'start',C.muted);
  s+=rect(22,134,396,54,C.white)+t(38,155,'补课  9/20（周日）→ 10/6（周二）',12,600)+t(38,175,'　　　 10/10（周六）→ 10/7（周三）',12,600);
  s+=rect(22,199,396,39,C.amber,C.amberLine)+t(220,224,'放假前在智慧学工（二期）如实填写离返校信息',13,700,'middle');
  return s;
};
const footer=(y=827)=>rect(70,y,300,48,C.amber,C.amberLine,24)+t(220,y+30,'完成节假日离校报备',16,700,'middle');

const pc=[['登录智慧学工','（二期）'],['专题服务','→ 学生请假'],['全日制学生节假日','离校报备'],['如实填写','离返校信息']];
const mobile=[['企业微信→工作台','→ 智慧学工'],['二期测试'],['专题服务→学生请假','→ 我的服务'],['全日制学生节假日','离校报备'],['如实填写','离返校信息']];

// 1. Each route snakes through a compact two-column block.
let a=header('方案一 · 折返路线');
a+=t(22,267,'电脑端',16,700,'start',C.blueLine)+path('M88 262 H418',C.blueLine,1);
const ax=[22,226,22,226], ay=[280,280,365,365];
pc.forEach((p,i)=>a+=card(ax[i],ay[i],192,60,String(i+1),p,'blue'));
a+=path('M214 310 H226 M322 340 V352 H118 V365 M214 395 H226',C.blueLine,2)+arrow(223,310,'right',C.blueLine)+arrow(118,362,'down',C.blueLine)+arrow(223,395,'right',C.blueLine);
a+=t(22,470,'移动端',16,700,'start',C.greenLine)+path('M88 465 H418',C.greenLine,1);
const mx=[22,226,22,226,22], my=[485,485,570,570,655];
mobile.forEach((p,i)=>a+=card(mx[i],my[i],192,60,String(i+1),p,'green'));
a+=path('M214 515 H226 M322 545 V557 H118 V570 M214 600 H226 M322 630 V642 H118 V655',C.greenLine,2)+arrow(223,515,'right',C.greenLine)+arrow(118,567,'down',C.greenLine)+arrow(223,600,'right',C.greenLine)+arrow(118,652,'down',C.greenLine);
a+=path('M118 715 V748 H220 V775',C.greenLine,2)+arrow(220,772,'down',C.greenLine)+footer(775);
writeFileSync(join(dir,'01-serpentine.svg'),svg(a));

// 2. Two compact loops with a clear central choice and clockwise route.
let b=header('方案二 · 回环双路线');
b+=rect(135,250,170,42,C.white,C.line,21)+t(220,277,'选择办理端',15,700,'middle');
b+=t(22,321,'电脑端  ①→②→③→④',15,700,'start',C.blueLine);
const bx=[22,226,226,22], by=[337,337,407,407];
pc.forEach((p,i)=>b+=card(bx[i],by[i],192,58,String(i+1),p,'blue',12.5));
b+=path('M214 366 H226 M322 395 V407 M226 436 H214',C.blueLine,2)+arrow(223,366,'right',C.blueLine)+arrow(322,404,'down',C.blueLine)+arrow(217,436,'left',C.blueLine);
b+=t(22,509,'移动端  ①→②→③→④→⑤',15,700,'start',C.greenLine);
const cx=[22,226,226,22,22], cy=[525,525,595,595,665];
mobile.forEach((p,i)=>b+=card(cx[i],cy[i],192,58,String(i+1),p,'green',12.5));
b+=path('M214 554 H226 M322 583 V595 M226 624 H214 M118 653 V665',C.greenLine,2)+arrow(223,554,'right',C.greenLine)+arrow(322,592,'down',C.greenLine)+arrow(217,624,'left',C.greenLine)+arrow(118,662,'down',C.greenLine);
b+=path('M118 723 V780 H220 V827',C.greenLine,2)+arrow(220,824,'down',C.greenLine)+footer();
writeFileSync(join(dir,'02-loop.svg'),svg(b));

// 3. A numbered two-column matrix, optimized for scanning at phone width.
let c=header('方案三 · 编号矩阵');
c+=rect(22,253,396,34,C.blue,C.blueLine,8)+t(38,276,'电脑端',15,700)+t(403,276,'按编号操作',11,500,'end',C.muted);
const dx=[22,226,22,226],dy=[301,301,369,369];
pc.forEach((p,i)=>c+=card(dx[i],dy[i],192,56,String(i+1),p,'blue',12.5));
c+=rect(22,457,396,34,C.green,C.greenLine,8)+t(38,480,'移动端',15,700)+t(403,480,'按编号操作',11,500,'end',C.muted);
const ex=[22,226,22,226,22],ey=[505,505,573,573,641];
mobile.forEach((p,i)=>c+=card(ex[i],ey[i],192,56,String(i+1),p,'green',12.5));
c+=path('M22 721 H418',C.line,1)+t(220,748,'电脑端与移动端任选其一',13,600,'middle',C.muted);
c+=footer(789);
writeFileSync(join(dir,'03-matrix.svg'),svg(c));
