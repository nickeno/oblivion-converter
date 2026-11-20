"""Builds packaging/app.ico from the app's own art: the gate sign on stone, with the glowing mouth."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
A = ROOT / 'osc' / 'ui' / 'assets'
N = 512
wall = Image.open(A / 'wall.jpg').convert('RGB')
bg = wall.crop((0, 0, 510, 510)).resize((N, N), Image.LANCZOS).point(lambda v: int(v * .55))
# the sign, cropped square around its middle (260, 284 in gate.png)
gate = Image.open(A / 'gate.png').convert('RGBA').crop((260 - 262, 284 - 262, 260 + 262, 284 + 262)).resize((N, N), Image.LANCZOS)
img = bg.convert('RGBA')
img.alpha_composite(gate)
# red light and the hot mouth in the middle
glow = Image.new('RGBA', (N, N), (0, 0, 0, 0))
d = ImageDraw.Draw(glow)
d.ellipse((N * .2, N * .34, N * .8, N * .74), fill=(215, 45, 8, 150))
glow = glow.filter(ImageFilter.GaussianBlur(N * .09))
img.alpha_composite(glow)
core = Image.new('RGBA', (N, N), (0, 0, 0, 0))
d = ImageDraw.Draw(core)
d.rounded_rectangle((N * .27, N * .455, N * .73, N * .625), radius=N * .085, fill=(120, 14, 2, 255))
d.rounded_rectangle((N * .285, N * .47, N * .715, N * .61), radius=N * .07, fill=(226, 71, 26, 255))
d.rounded_rectangle((N * .33, N * .495, N * .67, N * .575), radius=N * .04, fill=(255, 176, 74, 255))
core = core.filter(ImageFilter.GaussianBlur(N * .012))
img.alpha_composite(core)
# rounded corners
mask = Image.new('L', (N, N), 0)
ImageDraw.Draw(mask).rounded_rectangle((0, 0, N - 1, N - 1), radius=N * .22, fill=255)
img.putalpha(mask)
img.save(Path(__file__).with_name('app.png'))
img.save(Path(__file__).with_name('app.ico'), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print('icon written')
