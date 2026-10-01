from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
P=Path(__file__).resolve().parent
BG='#FAF7F0'; INK='#30322F'; ACC='#AA6249'; LINE='#DCD4C7'; CARD='#FFFDFA'
def font(n): return ImageFont.truetype('/System/Library/Fonts/Hiragino Sans GB.ttc',n)
def canvas(w,h,title,sub):
 im=Image.new('RGB',(w,h),BG); d=ImageDraw.Draw(im)
 d.text((44,35),title,font=font(42),fill=INK)
 d.text((44,100),sub,font=font(25),fill=ACC)
 return im,d
def text(d,x,y,s,n=28,color=INK):
 for i,l in enumerate(s.split('\n')): d.text((x,y+i*(n+10)),l,font=font(n),fill=color)
def box(d,xy,s,n=28):
 d.rounded_rectangle(xy,radius=14,fill=CARD,outline=LINE,width=2)
 lines=s.split('\n'); ht=len(lines)*(n+10)-10
 for i,l in enumerate(lines):
  length=d.textlength(l,font=font(n))
  d.text(((xy[0]+xy[2]-length)/2,(xy[1]+xy[3]-ht)/2+i*(n+10)),l,font=font(n),fill=INK)
def arrow(d,x,y1,y2):
 d.line((x,y1,x,y2-7),fill=ACC,width=3); d.polygon([(x,y2),(x-6,y2-10),(x+6,y2-10)],fill=ACC)
im,d=canvas(960,610,'2026 中秋·国庆假期安排','假期与补课日期')
box(d,(44,162,462,290),'中秋节\n9月25日—27日 · 3天',29)
box(d,(498,162,916,290),'国庆节\n10月1日—7日 · 7天',29)
text(d,44,328,'补课安排',30,ACC)
box(d,(44,384,916,465),'9月20日（周日）补10月6日（周二）的课',29)
box(d,(44,493,916,574),'10月10日（周六）补10月7日（周三）的课',29)
im.save(P/'flowchart.png')
im,d=canvas(1000,1070,'假期离校报备','各位同学须在放假前完成报备 · 按实际情况如实填写')
text(d,64,158,'电脑端',32,ACC); text(d,548,158,'移动端',32,ACC)
text(d,64,208,'建议使用 Chrome 浏览器',23)
left=['1  登录智慧学工（二期）','2  专题服务','3  学生请假','4  左侧目录选择\n全日制学生节假日离校报备','5  按实际情况如实填写']
right=['1  企业微信工作台','2  智慧学工','3  二期测试','4  专题服务','5  学生请假','6  我的服务','7  全日制学生\n节假日离校报备','8  按实际情况如实填写']
for x,items in [(44,left),(528,right)]:
 for i,s in enumerate(items):
  y=263+i*96; box(d,(x,y,x+428,y+76),s,25)
  if i+1<len(items): arrow(d,x+214,y+76,y+96)
im.save(P/'flowchart-02-reporting.png')
im,d=canvas(960,980,'中秋·国庆假期省流版','2026年假期安排与离校报备')
box(d,(44,155,916,283),'中秋：9月25日—27日\n国庆：10月1日—7日',30)
box(d,(44,307,916,431),'9月20日补10月6日的课\n10月10日补10月7日的课',30)
text(d,44,468,'各位同学：放假前完成离校报备',30,ACC)
text(d,44,535,'电脑端',29,ACC)
text(d,44,587,'智慧学工（二期）→ 专题服务 → 学生请假\n→ 左侧全日制学生节假日离校报备',27)
text(d,44,684,'移动端',29,ACC)
text(d,44,736,'企业微信工作台 → 智慧学工 → 二期测试\n→ 专题服务 → 学生请假 → 我的服务\n→ 全日制学生节假日离校报备',27)
text(d,44,892,'按自身实际情况如实填写',28,ACC)
im.save(P/'summary.png')
(P/'flowchart.mmd').write_text('''flowchart TB
  subgraph H[2026年假期安排]
    direction LR
    A["中秋节：9月25日—27日，共3天"]
    B["国庆节：10月1日—7日，共7天"]
  end
  subgraph C[补课安排]
    direction LR
    C1["9月20日（周日）补10月6日（周二）的课"]
    C2["10月10日（周六）补10月7日（周三）的课"]
  end
''',encoding='utf-8')
(P/'flowchart-02-reporting.mmd').write_text('''flowchart TB
  R["各位同学须在放假前完成离校报备"]
  R -->|电脑端| A1
  R -->|移动端| B1
  subgraph PC[电脑端 · 建议使用Chrome浏览器]
    A1["登录智慧学工（二期）"] --> A2["专题服务"] --> A3["学生请假"] --> A4["左侧目录：全日制学生节假日离校报备"] --> A5["按自身实际情况如实填写"]
  end
  subgraph MOBILE[移动端]
    B1["企业微信工作台"] --> B2["智慧学工"] --> B3["二期测试"] --> B4["专题服务"] --> B5["学生请假"] --> B6["我的服务"] --> B7["全日制学生节假日离校报备"] --> B8["按自身实际情况如实填写"]
  end
''',encoding='utf-8')
(P/'summary.mmd').write_text('''flowchart TB
  subgraph D[2026年假期与补课]
    H["中秋：9月25日—27日；国庆：10月1日—7日"]
    C["9月20日补10月6日的课；10月10日补10月7日的课"]
  end
  R["各位同学须在放假前完成离校报备"] -->|电脑端| P["电脑端：智慧学工（二期）"]
  R -->|移动端| M["移动端：企业微信工作台"]
  P --> P2["专题服务"] --> P3["学生请假"] --> P4["左侧目录：全日制学生节假日离校报备"] --> P5["按实际情况如实填写"]
  M --> M2["智慧学工"] --> M3["二期测试"] --> M4["专题服务"] --> M5["学生请假"] --> M6["我的服务"] --> M7["全日制学生节假日离校报备"] --> M8["按实际情况如实填写"]
''',encoding='utf-8')
