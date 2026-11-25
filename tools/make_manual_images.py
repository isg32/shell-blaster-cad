# Renders the visual-manual images for README.md from the live CAD model.
# Run inside the FreeCAD GUI (Macro, Python console, or the FreeCAD MCP):
#     exec(open('tools/make_manual_images.py').read())
# Images are written to docs/images/. Labels are drawn with Qt from the projected 3D anchor points.
import os, math, runpy
import FreeCAD as App, FreeCADGui as Gui, Part
from FreeCAD import Vector as V
try:
    from PySide6 import QtGui, QtCore
except ImportError:
    try:
        from PySide2 import QtGui, QtCore
    except ImportError:
        from PySide import QtGui, QtCore

ROOT = '/home/isg32/dev/cad/glock-18-realistic-toy'
OUT = os.path.join(ROOT, 'docs', 'images')
os.makedirs(OUT, exist_ok=True)
NS = runpy.run_path(os.path.join(ROOT, 'blaster.FCMacro'), run_name='manual')
SCALE = 2


def parts(slide_pos=0.0, cocked=False):
    g = NS['build_all'].__globals__
    g['SLIDE_POS'], g['COCKED'] = slide_pos, cocked
    NS['build_all']()
    out = {n: dict(p) for n, p in NS['PARTS'].items()}
    g['SLIDE_POS'], g['COCKED'] = 0.0, False
    NS['build_all']()                     # leave the model in its default state
    return out


def center(sh):
    bb = sh.BoundBox
    return V(bb.Center)


def shot(fname, items, direction=None, std=None, labels=(), zoom=1.0, title=None):
    """items: list of (name, shape, color, transparency). labels: list of (text, 3D point)."""
    if 'Shot' in App.listDocuments():
        App.closeDocument('Shot')
    doc = App.newDocument('Shot')
    for i, (n, sh, col, tr) in enumerate(items):
        o = doc.addObject('Part::Feature', 'P%02d' % i)
        o.Shape = sh
        o.ViewObject.ShapeColor = col
        o.ViewObject.Transparency = tr
        o.ViewObject.LineColor = (0.15, 0.15, 0.15)
    doc.recompute()
    view = Gui.getDocument('Shot').activeView()
    view.setCameraType('Orthographic')
    if std:
        getattr(view, std)()
    if direction:
        view.setViewDirection(direction)
    view.fitAll()
    Gui.updateGui()
    w, h = view.getSize()
    path = os.path.join(OUT, fname)
    fix_camera(view, zoom)                       # must be right before saving: a redraw resets the clip planes
    view.saveImage(path, w * SCALE, h * SCALE, 'White')
    proj = lambda p: (lambda q: (q[0] * SCALE, (h - q[1]) * SCALE))(view.getPointOnScreen(p))
    # calibrate label positions against what was actually drawn (projected vertices vs. ink extents)
    vx = []
    for _, sh, _, _ in items:
        for vtx in sh.Vertexes[::max(1, len(sh.Vertexes) // 400)]:
            vx.append(proj(vtx.Point))
    pts = [(text,) + proj(p) for text, p in labels]
    annotate(path, pts, title, vx)
    App.closeDocument('Shot')
    return path


def ink_box(img):
    """bounding box of non-white pixels (x0, y0, x1, y1), sampled every 2 px"""
    W, H = img.width(), img.height()
    xs, ys = [], []
    for y in range(0, H, 2):
        for x in range(0, W, 2):
            c = img.pixelColor(x, y)
            if c.red() < 235 or c.green() < 235 or c.blue() < 235:
                xs.append(x); ys.append(y)
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def fix_camera(view, zoom=1.0):
    """Off-screen rendering uses the camera's stored clip planes; push the camera back and open them wide."""
    from pivy import coin
    cam = view.getCameraNode()
    d = cam.orientation.getValue().multVec(coin.SbVec3f(0, 0, -1))
    p = cam.position.getValue()
    cam.position.setValue(p - d * 2000.0)
    cam.nearDistance.setValue(10.0)
    cam.farDistance.setValue(8000.0)
    try:
        cam.focalDistance.setValue(cam.focalDistance.getValue() + 2000.0)
    except Exception:
        pass
    if zoom != 1.0 and hasattr(cam, 'height'):
        cam.height.setValue(cam.height.getValue() / zoom)


def annotate(path, pts, title, vx=None):
    img = QtGui.QImage(path)
    W, H = img.width(), img.height()
    if vx:
        ink = ink_box(img)
        if ink:
            px0, px1 = min(v[0] for v in vx), max(v[0] for v in vx)
            py0, py1 = min(v[1] for v in vx), max(v[1] for v in vx)
            if px1 - px0 > 20 and py1 - py0 > 20:
                ax, ay = (ink[2] - ink[0]) / (px1 - px0), (ink[3] - ink[1]) / (py1 - py0)
                pts = [(t, ink[0] + (x - px0) * ax, ink[1] + (y - py0) * ay) for t, x, y in pts]
    pa = QtGui.QPainter(img)
    pa.setRenderHint(QtGui.QPainter.Antialiasing)
    font = QtGui.QFont('Sans', 11 * SCALE // 2 + 3)
    font.setBold(True)
    pa.setFont(font)
    fm = QtGui.QFontMetrics(font)
    placed = []
    cx, cy = W / 2.0, H / 2.0
    for text, x, y in pts:
        dx, dy = x - cx, y - cy
        d = math.hypot(dx, dy) or 1.0
        lx, ly = x + dx / d * 70 * SCALE, y + dy / d * 55 * SCALE
        tw = (fm.horizontalAdvance(text) if hasattr(fm, 'horizontalAdvance') else fm.width(text)) + 16
        th = fm.height() + 8
        lx = min(max(lx - tw / 2, 6), W - tw - 6)
        ly = min(max(ly - th / 2, 6), H - th - 6)
        r = QtCore.QRectF(lx, ly, tw, th)
        for _ in range(40):
            if not any(r.intersects(q) for q in placed):
                break
            r.translate(0, th + 4 if y > cy else -(th + 4))
            if r.top() < 0 or r.bottom() > H:
                r.translate(tw + 8, 0)
        placed.append(r)
        pa.setPen(QtGui.QPen(QtGui.QColor(30, 30, 30), 2))
        pa.drawLine(QtCore.QPointF(x, y), r.center())
        pa.setBrush(QtGui.QBrush(QtGui.QColor(30, 30, 30)))
        pa.drawEllipse(QtCore.QPointF(x, y), 4, 4)
        pa.setBrush(QtGui.QBrush(QtGui.QColor(255, 250, 225)))
        pa.drawRoundedRect(r, 6, 6)
        pa.drawText(r, QtCore.Qt.AlignCenter, text)
    if title:
        tf = QtGui.QFont('Sans', 14 * SCALE // 2 + 5)
        tf.setBold(True)
        pa.setFont(tf)
        pa.setPen(QtGui.QColor(20, 20, 20))
        pa.drawText(QtCore.QRectF(0, 8, W, 60), QtCore.Qt.AlignHCenter, title)
    pa.end()
    img.save(path)


def it(P, name, tr=0, move=V(0, 0, 0), color=None):
    p = P[name]
    return (name, p['shape'].translated(move), color or p['color'], tr if not p['alpha'] else max(tr, p['alpha']))


# =============================== the manual images ===============================
N = NS
G = lambda k: N[k]
GHOST = 82


def face_pt(sh, side, fx=0.5, fz=0.5):
    """a point on a bbox face (after mirroring: right side = -Y). side: right/left/top/bottom/front/rear"""
    b = sh.BoundBox
    x = b.XMin + fx * b.XLength
    z = b.ZMin + fz * b.ZLength
    y = b.YMin + 0.5 * b.YLength
    if side == 'right': y = b.YMin
    if side == 'left': y = b.YMax
    if side == 'top': z = b.ZMax
    if side == 'bottom': z = b.ZMin
    if side == 'front': x = b.XMax
    if side == 'rear': x = b.XMin
    return V(x, y, z)


def cyl_ref(r, x0, x1, y=0, z=0, axis='x'):
    if axis == 'x':
        return Part.makeCylinder(r, x1 - x0, V(x0, y, z), V(1, 0, 0))
    if axis == 'y':
        return Part.makeCylinder(r, x1 - x0, V(y, x0, z), V(0, 1, 0))
    return Part.makeCylinder(r, x1 - x0, V(y, z, x0), V(0, 0, 1))


SKIP = ('Dart_ref',)
def all_items(P, ghost=(), hide=(), shells=False, refs=False):
    out = []
    for n in P:
        if n in hide or n in SKIP and not refs: continue
        if n.endswith('_ref') and not refs: continue
        if n.startswith('Shell_Mag') and not shells: continue
        out.append(it(P, n, GHOST if n in ghost else 0))
    return out


def section(P, keep_left=True):
    cutter = Part.makeBox(600, 300, 600, V(-300, 0, -300)) if keep_left else Part.makeBox(600, 300, 600, V(-300, -300, -300))
    out = []
    for n, p in P.items():
        if n.startswith('Shell_Mag') and n not in ('Shell_Mag1', 'Shell_Mag2', 'Shell_Mag3', 'Shell_Mag4',
                                                    'Shell_Mag5', 'Shell_Mag6', 'Shell_Mag7', 'Shell_Mag8'):
            continue
        sh = p['shape'].common(cutter)
        if sh.Volume < 1e-3: continue
        out.append((n, sh, p['color'], 0))
    return out


def make_all():
    imgs = []
    P = parts()
    sl, mz, rel = P['Slide']['shape'], P['Muzzle_Orange']['shape'], P['Mag_Release']['shape']
    fr, fl, mag = P['Frame_R']['shape'], P['Frame_L']['shape'], P['Mag_Body']['shape']
    trig = P['Trigger']['shape']
    # 1 overview
    lab = [('Slide (rack it back & forward)', face_pt(sl, 'top', 0.35)),
           ('Ejection port', face_pt(sl, 'right', 0.62, 0.55)),
           ('Orange muzzle cap', face_pt(mz, 'front', 0.5, 0.55)),
           ('Front handle', face_pt(fr, 'right', 0.70, 0.30)),
           ('Extended magazine (8 shells)', face_pt(mag, 'right', 0.5, 0.15)),
           ('Mag release button', face_pt(rel, 'right', 0.5, 0.6)),
           ('Trigger', face_pt(trig, 'right', 0.4, 0.2)),
           ('Rear grip', V(-150, -17, -70))]
    imgs.append(shot('01_overview.png', all_items(P), std='viewIsometric', labels=lab, title='Overview'))
    # 2/3 sides
    imgs.append(shot('02_right_side.png', all_items(P), direction=(0.0, 1.0, -0.03), title='Right side', labels=[
        ('Ejection port', face_pt(sl, 'right', 0.62, 0.55)), ('Mag release button', face_pt(rel, 'right', 0.5, 0.6)),
        ('Trigger', face_pt(trig, 'right', 0.4, 0.2)), ('Side groove (styling)', V(-20, -17, G('GROOVE_Z'))),
        ('Racking pad', V(G('BODY_REAR') + 20, -17, 5.0))]))
    imgs.append(shot('03_left_side.png', all_items(P), direction=(0.0, -1.0, -0.03), title='Left side', labels=[
        ('Printed frame pins', V(-60, 17, G('FRAME_BOT') + 10.2)), ('Orange muzzle cap', face_pt(mz, 'left', 0.5, 0.5))]))
    # 4/5 sections
    def sec_labels(P, back=False):
        sx = -G('STROKE') if back else 0.0
        return [('Plunger head + O-ring', V(G('HEAD_FRONT') - G('HEAD_L') / 2 + sx, 0, 6)),
                ('Main spring', V((G('TUBE_REAR') + G('HEAD_FRONT')) / 2 + sx, 0, 7.5)),
                ('Plunger rod', V(G('FLANGE_REAR') - 5 + sx, 0, 0)),
                ('Catch (sear)', V(G('TOOTH_X'), 0, -4)),
                ('Trigger', V(G('TRIG_X0') + 3, 0, G('TRIG_Z0') - 10)),
                ('Nozzle', V(-12 + sx, 0, 0)),
                ('Shell + dart in chamber' if not back else 'Next shell up under the lips', V(12, 0, 0) if not back else V(-15, 0, 0)),
                ('Magazine + follower', V(-15, 0, -60)),
                ('Barrel', V(50, 0, 0)),
                ('Mag release latch', V((G('REL_X0') + G('REL_X1')) / 2, 0, G('REL_Z0') + 2))]
    imgs.append(shot('04_cutaway.png', section(P), direction=(0.0, 1.0, -0.03), labels=sec_labels(P), title='Cutaway (slide forward)'))
    Pb = parts(slide_pos=1.0)
    imgs.append(shot('05_cutaway_racked.png', section(Pb), direction=(0.0, 1.0, -0.03), labels=sec_labels(Pb, True),
                     title='Cutaway (slide racked back: catch holds the rod)'))
    # 6 exploded (outer parts; internals have their own close-ups)
    off = {'Slide': V(0, 0, 70), 'Frame_L': V(0, 60, 0), 'Frame_R': V(0, -10, 0), 'Muzzle_Orange': V(45, 0, 0),
           'Mag_Body': V(0, 0, -80), 'Mag_Follower': V(0, 0, -80), 'Mag_Base': V(0, 0, -115), 'Mag_Release': V(0, -55, 0),
           'Trigger': V(0, -10, 0), 'Trigger_Bar': V(0, -10, 0), 'Catch': V(0, -10, 0)}
    names = {'Slide': 'Slide (bolt + plunger inside)', 'Frame_L': 'Frame L', 'Frame_R': 'Frame R',
             'Muzzle_Orange': 'Orange muzzle cap', 'Mag_Body': 'Magazine', 'Mag_Base': 'Mag base plate',
             'Mag_Release': 'Mag release'}
    items, labs = [], []
    for n in P:
        if n.endswith('_ref') or n.startswith('Shell') or n == 'Dart_ref': continue
        mv = off.get(n, V(0, 0, 0))
        if n in ('Bolt', 'Extractor', 'TubeCap', 'Plunger_Head', 'Plunger_Rod'):
            mv = off['Slide']
        items.append(it(P, n, 0, mv))
        if n in names:
            side = 'left' if n == 'Frame_L' else 'top' if n == 'Slide' else 'right'
            labs.append((names[n], face_pt(P[n]['shape'].translated(mv), side, 0.5, 0.5)))
    imgs.append(shot('06_exploded.png', items, std='viewIsometric', labels=labs, title='Exploded view (main parts)'))
    # 7 print plate
    pr = [n for n in P if P[n]['printable'] and not n.startswith('Shell_Mag')]
    order = ['Frame_R', 'Frame_L', 'Slide', 'Mag_Body', 'Bolt', 'Muzzle_Orange', 'Plunger_Rod', 'Trigger_Bar',
             'TubeCap', 'Plunger_Head', 'Mag_Base', 'Mag_Follower', 'Trigger', 'Mag_Release', 'Catch', 'Extractor', 'Shell_Chambered']
    pr = [n for n in order if n in pr] + [n for n in pr if n not in order]
    x, y, rowh, items, labs = 0.0, 0.0, 0.0, [], []
    for n in pr:
        s_ = N['print_shape'](n)
        bb = s_.BoundBox
        if x + bb.XLength > 520:
            x, y, rowh = 0.0, y + rowh + 25, 0.0
        s_ = s_.translated(V(x - bb.XMin, y - bb.YMin, 0))
        items.append((n, s_, P[n]['color'], 0))
        labs.append((n.replace('_', ' ') + ('  x10' if n == 'Shell_Chambered' else ''), face_pt(s_, 'top', 0.5, 1.0)))
        x += bb.XLength + 25
        rowh = max(rowh, bb.YLength)
    imgs.append(shot('07_print_plate.png', items, direction=(0.25, 0.55, -1.0), labels=labs,
                     title='Every printed part, in print orientation (as in stl/)'))
    # 8 bolt / plunger sub-assembly
    offs = {'Bolt': V(0, 0, 0), 'Extractor': V(0, 0, 18), 'TubeCap': V(-35, 0, 0), 'Plunger_Head': V(-80, 0, 0),
            'Plunger_Rod': V(-80, 0, 0)}
    items = [it(P, n, 0, mv) for n, mv in offs.items()]
    spr = P['MainSpring_ref']['shape'].translated(V(-57, 0, 0))
    items.append(('spring', spr, (0.55, 0.57, 0.6), 40))
    labs = [('Bolt: tube + nozzle (one part)', face_pt(P['Bolt']['shape'], 'top', 0.4)),
            ('Extractor (press into rib)', face_pt(P['Extractor']['shape'].translated(offs['Extractor']), 'top', 0.5)),
            ('Tube cap (quarter-turn bayonet)', face_pt(P['TubeCap']['shape'].translated(offs['TubeCap']), 'top', 0.5)),
            ('Main spring', face_pt(spr, 'top', 0.5)),
            ('Plunger head (O-ring groove)', face_pt(P['Plunger_Head']['shape'].translated(offs['Plunger_Head']), 'top', 0.5)),
            ('Plunger rod (notch near the tail)', face_pt(P['Plunger_Rod']['shape'].translated(offs['Plunger_Rod']), 'top', 0.15)),
            ('Nozzle', V(-10, 0, 4.5)), ('Bayonet slots', V(G('TUBE_REAR') + 2, -12, 0))]
    imgs.append(shot('08_bolt_plunger.png', items, direction=(-0.5, 0.7, -0.5), labels=labs,
                     title='Bolt + plunger sub-assembly (exploded)'))
    # 9 magazine
    mb = P['Mag_Body']['shape']
    sh1 = P['Shell_Mag1']['shape']
    items = [it(P, 'Mag_Body', 30), it(P, 'Mag_Follower', 0, V(0, 0, -50)), it(P, 'Mag_Base', 0, V(0, 0, -40)),
             ('shell', sh1.translated(V(0, 0, 45)), P['Shell_Mag1']['color'], 0),
             ('spring', cyl_ref(5.5, G('MAG_BODY_BOT') + 5 - 40, G('FOLLOWER_TOP') - 50 - 6, y=0, z=0, axis='z')
              .translated(V((G('MAG_IN_X0') + G('MAG_IN_X1')) / 2, 0, 0)), (0.55, 0.57, 0.6), 60)]
    labs = [('Feed lips', face_pt(mb, 'top', 0.55)), ('Ejector post', V(G('POST_X0') + 1, 9, 5)),
            ('Shell (rim to the rear)', face_pt(sh1.translated(V(0, 0, 45)), 'top', 0.5)),
            ('Release catch tab', V(G('LUG_X0') + 1, 0, G('REL_Z1') + 1.5)),
            ('Follower', face_pt(P['Mag_Follower']['shape'].translated(V(0, 0, -50)), 'right', 0.5)),
            ('Mag spring (~160-170 mm)', V((G('MAG_IN_X0') + G('MAG_IN_X1')) / 2, -5.5, -120)),
            ('Base plate (snaps on)', face_pt(P['Mag_Base']['shape'].translated(V(0, 0, -40)), 'right', 0.5))]
    imgs.append(shot('09_magazine.png', items, direction=(-0.6, 0.6, -0.5), labels=labs, title='Magazine (exploded)'))
    # 10 trigger + catch (frame ghosted)
    rodb = P['Plunger_Rod']['shape']
    pin = cyl_ref(G('PIN_D') / 2, -11, 11, y=G('PIVOT_X'), z=G('PIVOT_Z'), axis='y')  # filament
    items = [it(P, 'Frame_R', GHOST), it(P, 'Catch'), it(P, 'Trigger'), it(P, 'Trigger_Bar'),
             ('pin', pin, (0.55, 0.57, 0.6), 0), it(P, 'Spring_Trigger'), it(P, 'Spring_Catch'),
             ('rod', rodb.translated(V(-G('STROKE'), 0, 0)), P['Plunger_Rod']['color'], 50)]
    labs = [('Catch lever', V(G('TOOTH_X') - 2, 0, -4)), ('Pivot pin (1.75 mm filament)', V(G('PIVOT_X'), 3, G('PIVOT_Z'))),
            ('Catch foot', V(G('PIVOT_X'), -6, G('FOOT_Z0') + 1)), ('Trigger bar pushes the foot', V(G('PUSH_X') + 15, -13, G('TRIG_Z0') + 4)),
            ('Trigger (slides back 6 mm)', face_pt(trig, 'left', 0.3, 0.3)), ('Printed return spring', V(G('TRIG_X0') + 15, 0, G('TRIG_Z0') + 2.5)),
            ('Rod notch (when racked back)', V(G('ROD_TAIL_BACK') + 3.75, 0, 3))]
    sub = [x for x in items]
    imgs.append(shot('10_trigger_catch.png', sub, direction=(0.35, -0.75, -0.55), labels=labs,
                     title='Trigger + catch (frame ghosted)', zoom=1.0))
    # 11 mag release
    items = [it(P, 'Frame_R', GHOST), it(P, 'Mag_Release'), it(P, 'Spring_Release'), it(P, 'Mag_Body', 40)]
    labs = [('Mag release latch', face_pt(rel, 'right', 0.5, 0.9)), ('Button (press to drop the mag)', face_pt(rel, 'right', 0.5, 0.5)),
            ('Printed zig-zag return spring', center(P['Spring_Release']['shape'])), ('Catch tab on the mag', V(G('LUG_X0') + 1, 0, G('REL_Z1') + 1.5))]
    imgs.append(shot('11_mag_release.png', items, direction=(0.45, 0.8, -0.4), labels=labs, title='Mag release (frame ghosted)'))
    # 12 ejection
    te = G('STROKE') - G('EJECT_REMAIN')
    shell = P['Shell_Chambered']['shape']
    piv = V(G('SHELL_REAR_CH') - te + G('RIM_T'), 0, 0)
    items = all_items(P, hide=('Slide', 'Bolt', 'Extractor', 'TubeCap', 'Shell_Chambered', 'Plunger_Head', 'Plunger_Rod', 'Dart_ref'))
    for n in ('Slide', 'Bolt', 'Extractor', 'TubeCap', 'Plunger_Head', 'Plunger_Rod'):
        items.append(it(P, n, 55 if n == 'Slide' else 0, V(-te, 0, 0)))
    for k, ang in enumerate((0, 25, 50)):
        items.append(('shell%d' % k, shell.translated(V(-te, 0, 0)).rotated(piv, V(0, 0, 1), -ang if N['RIGHT'] < 0 else ang),
                      P['Shell_Chambered']['color'], 0 if k == 2 else 55))
    labs = [('Ejector post stops the rim', V(G('POST_X0') + 1, 8, 3)),
            ('Shell swings out of the port', center(shell.translated(V(-te, 0, 0)).rotated(piv, V(0, 0, 1), -50))),
            ('Extractor hook pulls the shell back', V(-te + 0.5, 0, G('RIM_D') / 2 + 1))]
    imgs.append(shot('12_ejection.png', items, direction=(-0.2, 0.45, -1.0), labels=labs,
                     title='Ejection (slide 4 mm from fully back)'))
    # 13.. assembly steps (inside of Frame_R)
    inside = (0.12, -1.0, -0.32)
    fr_lab = [('Slide rails', V(-80, 0, G('RAIL_Z1'))), ('Chamber + barrel', V(20, 0, 0)), ('Magwell', V(-15, 0, -45)),
              ('Catch pocket', V(G('TOOTH_X'), 0, -6)), ('Trigger channel', V(G('TRIG_X0') + 12, 0, G('TRIG_Z0') + 2)),
              ('Holes for the printed pins', V(-60, -17, G('FRAME_BOT') + 10.2))]
    imgs.append(shot('13_step1_frame_R.png', [it(P, 'Frame_R')], direction=inside, labels=fr_lab,
                     title='Step 1: Frame R, split face up'))
    s2 = [it(P, 'Frame_R'), it(P, 'Catch'), it(P, 'Spring_Catch'), it(P, 'Trigger'), it(P, 'Trigger_Bar'), it(P, 'Spring_Trigger'), ('pin', pin, (0.55, 0.57, 0.6), 0)]
    imgs.append(shot('14_step2_catch_trigger.png', s2, direction=inside, title='Step 2: catch + filament pin, trigger + bar + printed springs',
                     labels=[('Catch + 1.75 mm filament pin', V(G('PIVOT_X') + 2, 0, -5)), ('Trigger + bar', V(G('TRIG_X0') + 10, 0, G('TRIG_Z0'))),
                             ('Bar end sits in front of the catch foot', V(G('PUSH_X'), 0, G('TRIG_Z0') + 2))]))
    s3 = s2 + [it(P, 'Mag_Release'), it(P, 'Spring_Release')]
    imgs.append(shot('15_step3_mag_release.png', s3, direction=inside, title='Step 3: mag release latch + spring',
                     labels=[('Mag release latch', center(rel))]))
    s4 = s3 + [it(P, n) for n in ('Bolt', 'Extractor', 'TubeCap', 'Plunger_Head', 'Plunger_Rod')] + [it(P, 'Slide', 60)]
    imgs.append(shot('16_step4_slide.png', s4, direction=inside, title='Step 4: slide (with bolt screwed in) onto the rails',
                     labels=[('Slide (shown see-through)', face_pt(sl, 'top', 0.3)), ('Bolt + plunger inside', V(-60, 0, 12))]))
    s5 = all_items(P, hide=('Muzzle_Orange', 'Mag_Body', 'Mag_Follower', 'Mag_Base'))
    imgs.append(shot('17_step5_close.png', s5, std='viewIsometric', title='Step 5: close with Frame L, press in the 7 printed pins',
                     labels=[('Frame L', face_pt(fl, 'top', 0.3)), ('Press in the 7 printed pins', V(-60, -17, G('FRAME_BOT') + 10.2))]))
    s6 = all_items(P, hide=('Mag_Body', 'Mag_Follower', 'Mag_Base'))
    s6 += [it(P, n, 0, V(0, 0, -60)) for n in ('Mag_Body', 'Mag_Base')]
    imgs.append(shot('18_step6_muzzle_mag.png', s6, std='viewIsometric', title='Step 6: glue the muzzle cap, push the mag in until it clicks',
                     labels=[('Orange muzzle cap (glue)', face_pt(mz, 'front', 0.5, 0.6)),
                             ('Mag goes up into the front handle', face_pt(mag.translated(V(0, 0, -60)), 'right', 0.5, 0.5))]))
    return imgs
