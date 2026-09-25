import { writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const dir = dirname(fileURLToPath(import.meta.url));
const themes = [
  { id: 'visual-01-warm-paper', name: '暖纸质', paper: '#FAF7F0', ink: '#2D332F', muted: '#68716A', accent: '#AA6249', accentText: '#FFFFFF', secondary: '#60796B', line: '#D8D2C6', dateA: '#FFFDF9', dateB: '#FFFDF9', cardA: '#FFFDF9', cardB: '#FFFDF9', alert: '#F3E6D9', alertInk: '#713F2E', end: '#E9EEE6', radius: 8, header: 'plain', cardStyle: 'stripe' },
  { id: 'visual-03-sage', name: '鼠尾草绿', paper: '#F5F5EC', ink: '#2C4035', muted: '#617467', accent: '#3F735A', accentText: '#FFFFFF', secondary: '#64836B', line: '#CAD7C8', dateA: '#E9F0E6', dateB: '#E9F0E6', cardA: '#FCFDF9', cardB: '#FCFDF9', alert: '#E1EBDD', alertInk: '#325D46', end: '#D5E5D5', radius: 18, header: 'plain', cardStyle: 'pill' },
];

const pc = [['登录智慧学工', '（二期）'], ['专题服务', '→ 学生请假'], ['全日制学生节假日', '离校报备'], ['如实填写', '离返校信息']];
const mobile = [['企业微信→工作台', '→ 智慧学工'], ['二期测试'], ['专题服务→学生请假', '→ 我的服务'], ['全日制学生节假日', '离校报备'], ['如实填写', '离返校信息']];
const escape = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
const rect = (x,y,w,h,fill,stroke='none',r=0,sw=1) => `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${r}" fill="${fill}" stroke="${stroke}" stroke-width="${sw}"/>`;
const line = (d,color,width=1.5) => `<path d="${d}" fill="none" stroke="${color}" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round"/>`;
const text = (x,y,value,size,weight,color,anchor='start') => `<text x="${x}" y="${y}" fill="${color}" font-size="${size}" font-weight="${weight}" text-anchor="${anchor}">${escape(value)}</text>`;
const arrow = (x,y,direction,color) => direction==='right' ? line(`M${x-6} ${y-4} L${x} ${y} L${x-6} ${y+4}`,color,2) : line(`M${x-4} ${y-6} L${x} ${y} L${x+4} ${y-6}`,color,2);

function render(theme) {
  const C = theme;
  let s = rect(0,0,440,900,C.paper);
  if (C.header==='band') s += rect(0,0,440,55,C.accent);
  const titleColor=C.header==='band' ? '#FFFFFF' : C.ink;
  s += text(22,39,'中秋·国庆｜学生离校报备',22,750,titleColor);
  if (C.header==='rule') s += rect(22,51,396,3,C.accent);
  const date = (x,fill,top,bottom) => {
    let v = rect(x,67,192,61,fill,C.header==='plum'?'none':C.line,C.radius);
    if (C.cardStyle==='stripe') v += rect(x,67,192,4,C.accent,'none',2);
    const light=C.cardStyle==='number';
    v += text(x+16,93,top,15,700,light?'#FFFFFF':C.ink);
    v += text(x+16,114,bottom,11,550,light?'#E9E0EE':C.muted);
    return v;
  };
  s += date(22,C.dateA,'中秋  9月25—27日','共 3 天');
  s += date(226,C.dateB,'国庆  10月1—7日','共 7 天');
  s += rect(22,140,396,53,C.cardA,C.line,C.radius);
  s += text(37,161,'补课  9/20（周日）补 10/6（周二）',12,600,C.ink);
  s += text(37,181,'　　  10/10（周六）补 10/7（周三）',12,600,C.ink);
  s += rect(22,205,396,41,C.alert,'none',C.radius);
  s += text(220,231,'放假前完成离校报备，如实填写离返校信息',13,700,C.alertInk,'middle');

  const section = (name,y,color) => {
    let out = text(22,y,name,16,750,color);
    out += line(`M88 ${y-5} H418`,C.line,1);
    return out;
  };
  const card=(x,y,num,parts,color,fill)=>{
    let out=rect(x,y,192,62,fill,C.line,C.radius,1.15);
    if (C.cardStyle==='stripe') out+=rect(x,y,4,62,color,'none',2);
    if (C.cardStyle==='outline') out+=rect(x,y,192,62,'none',color,C.radius,1.2);
    if (C.cardStyle==='number') {
      out+=text(x+15,y+25,num,22,800,color);
    } else {
      out+=`<circle cx="${x+23}" cy="${y+22}" r="13" fill="${color}"/>`;
      out+=text(x+23,y+27,num,12,750,C.accentText,'middle');
    }
    const tx=x+108;
    if(parts.length===1) out+=text(tx,y+38,parts[0],13,650,C.ink,'middle');
    else { out+=text(tx,y+29,parts[0],12.7,650,C.ink,'middle'); out+=text(tx,y+47,parts[1],12.7,650,C.ink,'middle'); }
    return out;
  };
  const routes=(ys,color,count)=>{
    let out='';
    for(let i=0;i<count-1;i++) {
      const x1=i%2===0?214:322, x2=i%2===0?226:118;
      if(i%2===0){out+=line(`M${x1} ${ys[i]+31} H${x2}`,color,2);out+=arrow(224,ys[i]+31,'right',color);}
      else {const mid=ys[i]+71;out+=line(`M${x1} ${ys[i]+62} V${mid} H${x2} V${ys[i+1]}`,color,2);out+=arrow(x2,ys[i+1]-2,'down',color);}
    }
    return out;
  };
  s+=section('电脑端',271,C.accent);
  const py=[284,284,366,366],px=[22,226,22,226];
  s+=routes(py,C.accent,4);
  pc.forEach((parts,i)=>s+=card(px[i],py[i],String(i+1),parts,C.accent,C.cardA));
  s+=section('移动端',471,C.secondary);
  const my=[484,484,566,566,648],mx=[22,226,22,226,22];
  s+=routes(my,C.secondary,5);
  mobile.forEach((parts,i)=>s+=card(mx[i],my[i],String(i+1),parts,C.secondary,C.cardB));
  s+=line('M118 710 V751 H220 V778',C.secondary,2)+arrow(220,777,'down',C.secondary);
  const endInk=C.cardStyle==='number'?'#FFFFFF':C.ink;
  s+=rect(68,780,304,53,C.end,'none',C.radius);
  s+=text(220,814,'完成节假日离校报备',16,750,endInk,'middle');
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 440 900" width="880" height="1800" role="img" aria-label="中秋国庆学生离校报备流程"><style>text{font-family:'PingFang SC','Noto Sans SC','Microsoft YaHei',sans-serif}</style>${s}</svg>`;
}

const style = process.argv[2] ?? 'paper';
const choices = new Map([['paper',themes[0]],['sage',themes[1]]]);
if (style !== 'all' && !choices.has(style)) throw new Error(`未知视觉样式：${style}。可选 paper、sage、all。`);
for (const theme of style==='all' ? themes : [choices.get(style)]) writeFileSync(join(dir,`${theme.id}.svg`),render(theme));
