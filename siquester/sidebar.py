"""PackageList and Sidebar widgets."""

from .qt import *
from .constants import *
from .util import *
from .stats import *
from .persistence import *
from .widgets_common import *

class PackageList(QWidget):
    item_selected=pyqtSignal(int); delete_requested=pyqtSignal(int)
    reorder_requested=pyqtSignal(int,int); move_to_tab=pyqtSignal(int,int)
    rename_requested=pyqtSignal(int, str)   # real_idx, new_name
    def __init__(self,tab_id,tabs_ref,parent=None):
        super().__init__(parent); self.tab_id=tab_id; self._tabs=tabs_ref
        self._real_indices: list[int]=[]; self.setStyleSheet(_SS_TRANSPARENT)
        lay=QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        self.lst=PkgListWidget()
        self.lst.currentRowChanged.connect(lambda r: self.item_selected.emit(self._real_indices[r]) if 0<=r<len(self._real_indices) else None)
        self.lst.reorder_real.connect(self.reorder_requested.emit)
        lay.addWidget(self.lst)

    def _make_row(self,ds,real_idx):
        avg_t,avg_r=ds_avgs(ds); pct=stats_pct(ds.get("stats","")); pkg=ds["pkg_name"]
        size=ds.get("pkg_size",""); dur=ds.get("total_duration_sec",0)
        nr=len(ds["rounds"]); total_q=sum(sum(len(t["questions"]) for t in rd["themes"]) for rd in ds["rounds"])
        hl=get_hl(pkg)
        row_w=QWidget()
        if hl: bg,bd,_=hl; row_w.setStyleSheet(f"background:{bg};border:1px solid {bd};border-radius:5px;")
        else: row_w.setStyleSheet(_SS_TRANSPARENT)
        rl=QHBoxLayout(row_w); rl.setContentsMargins(10,3,4,3); rl.setSpacing(5)
        col=QVBoxLayout(); col.setSpacing(1)
        nc=hl[2] if hl else "#cdd6f4"
        nm=QLabel(pkg); nm.setStyleSheet(f"background:transparent;color:{nc};font-size:11px;font-weight:700;")
        nm.setWordWrap(False); nm.setMaximumWidth(178); nm.setToolTip("Двойной клик — переименовать пакет")
        nm.mouseDoubleClickEvent = lambda e, ri=real_idx, cur=pkg: self._rename_pkg(ri, cur)
        col.addWidget(nm)
        sr=QHBoxLayout(); sr.setSpacing(5); sr.setContentsMargins(0, 0, 0, 0)
        for val,clr,icon in [(avg_t,"#f9e2af","🟡"),(avg_r,"#a6e3a1","🟢")]:
            p=QLabel(f"{icon}{val:.0f}%"); p.setStyleSheet(f"background:transparent;color:{clr};font-size:10px;font-weight:700;"); sr.addWidget(p)
        if pct>0: gm=QLabel(f"🎮{pct:.0f}%"); gm.setStyleSheet("background:transparent;color:#cba6f7;font-size:10px;font-weight:700;"); sr.addWidget(gm)
        sr.addStretch(); col.addLayout(sr)
        meta=[f"{nr} раунд{'а' if nr==2 else 'ов' if nr>=5 else ''}",f"{total_q} вопр."]
        if size: meta.append(size)
        if dur>0: meta.append(f"⏱{fmt_dur(dur)}")
        col.addWidget(_lbl(" · ".join(meta),"background:transparent;color:#9399b2;font-size:10px;"))
        rl.addLayout(col,stretch=1)
        db=AnimatedButton("✕"); db.setObjectName(_ON_BTN_DEL); db.setFixedSize(20,20)
        db.clicked.connect(lambda _,i=real_idx: self.delete_requested.emit(i))
        rl.addWidget(db,alignment=_AlignTop)
        row_w.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        row_w.customContextMenuRequested.connect(lambda pos,ri=real_idx: self._ctx(ri,row_w.mapToGlobal(pos)))
        return row_w

    def _ctx(self,real_idx,gpos):
        if not self._tabs: return
        menu=QMenu(self); menu.addSection("Переместить в вкладку")
        for tab in self._tabs:
            if tab["id"]==self.tab_id: continue
            act=menu.addAction(tab["name"]); act.setData((real_idx,tab["id"]))
        chosen=menu.exec(gpos)
        if chosen and chosen.data(): ri,tid=chosen.data(); self.move_to_tab.emit(ri,tid)

    def _rename_pkg(self, real_idx: int, cur_name: str):
        new_name, ok = QInputDialog.getText(self, "Переименовать пакет", "Новое название:", text=cur_name)
        if ok and new_name.strip() and new_name.strip() != cur_name:
            self.rename_requested.emit(real_idx, new_name.strip())

    def rebuild(self, all_datasets, sort_mode, tabs):
        self._tabs = tabs; self._real_indices = []; self.lst.clear()
        filtered = [(i,ds) for i,ds in enumerate(all_datasets)
                    if self.tab_id == 0 or ds.get("tab_id", 0) == self.tab_id]
        if sort_mode == SORT_COMPLETION:
            filtered.sort(key=lambda x: -stats_pct(x[1].get("stats", "")))
        elif sort_mode in (SORT_TRIES, SORT_RIGHT):
            # Pre-compute avgs once per ds to avoid O(n²) recomputation in sort key
            avgs = {i: ds_avgs(ds) for i, ds in filtered}
            col = 0 if sort_mode == SORT_TRIES else 1
            filtered.sort(key=lambda x: -avgs[x[0]][col])
        for real_idx, ds in filtered:
            self._real_indices.append(real_idx)
            item = QListWidgetItem(); item.setSizeHint(QSize(216, 70))
            self.lst.addItem(item); self.lst.setItemWidget(item, self._make_row(ds, real_idx))
        self.lst._real_indices = list(self._real_indices)

    def select_by_real(self,real_idx):
        if real_idx in self._real_indices: self.lst.setCurrentRow(self._real_indices.index(real_idx))
    def current_real_idx(self):
        row=self.lst.currentRow(); return self._real_indices[row] if 0<=row<len(self._real_indices) else -1


class Sidebar(QWidget):
    item_selected=pyqtSignal(int); add_requested=pyqtSignal()
    delete_requested=pyqtSignal(int); reorder_requested=pyqtSignal(int,int)
    move_to_tab=pyqtSignal(int,int); rename_requested=pyqtSignal(int,str)
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setMinimumWidth(0); self.setMaximumWidth(248)
        # НЕ ставим WA_OpaquePaintEvent: это «обещание» закрасить каждый пиксель,
        # но прозрачные внутренние области (pane QTabWidget, угловой «+») его не
        # выполняли — и при переключении вкладок SI-HYX там оставались СТАРЫЕ
        # пиксели соседней вкладки (карточка аниме из ShikimoriHYX рядом с «Все»).
        # Без этого флага Qt перерисовывает фон сайдбара каждый раз — артефакта нет.
        self.setAttribute(Qt.WidgetAttribute.WA_PendingMoveEvent, False)
        self.setStyleSheet("background:#11111b;border-right:1px solid #313244;")
        # Clip children so they don't paint outside our bounds during animation
        self.setContentsMargins(0, 0, 0, 0)
        self._tabs=load_tabs(); self._next_id=max(t["id"] for t in self._tabs)+1 if self._tabs else 1
        self._sort_mode=SORT_NONE; self._datasets=[]; self._pkg_lists=[]
        lay=QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        hdr=QFrame(); hdr.setFixedHeight(38); hdr.setStyleSheet(_SS_TOPBAR)
        hl=QHBoxLayout(hdr); hl.setContentsMargins(8,0,6,0); hl.setSpacing(4); hl.addStretch()
        self._sort_btns=[]
        for tip,emoji in [("Завершение","🎮"),("Попытки","🟡"),("Правильные","🟢")]:
            sb=AnimatedButton(emoji); sb.setObjectName(_ON_BTN_SORT); sb.setToolTip(tip); sb.setCheckable(True); sb.setFixedSize(28,24)
            mode=[SORT_COMPLETION,SORT_TRIES,SORT_RIGHT][len(self._sort_btns)]
            sb.clicked.connect(lambda _,m=mode: self._on_sort(m)); hl.addWidget(sb); self._sort_btns.append(sb)
        lay.addWidget(hdr)
        self.tab_widget=QTabWidget()
        # Непрозрачный фон панели вкладок сайдбара — иначе сквозь прозрачный pane
        # просвечивали старые пиксели соседней вкладки SI-HYX (см. коммент выше).
        self.tab_widget.setStyleSheet("QTabWidget::pane{background:#11111b;border:none;}")
        self.tab_widget.tabBarDoubleClicked.connect(self._rename_tab)
        self.tab_widget.setCornerWidget(self._corner()); self.tab_widget.currentChanged.connect(lambda _: self.rebuild(self._datasets))
        lay.addWidget(self.tab_widget,stretch=1)
        self._rebuild_tabs()

    def _corner(self):
        # Угловой виджет с «+» — непрозрачный фон (#11111b), иначе в его области
        # (справа от «Все») оставались старые пиксели соседней вкладки SI-HYX.
        w=QWidget(); w.setStyleSheet("background:#11111b;")
        lay=QHBoxLayout(w); lay.setContentsMargins(2,0,4,0)
        btn=AnimatedButton("＋"); btn.setObjectName("btn_tab_add"); btn.setFixedSize(22,22); btn.clicked.connect(self._add_tab); lay.addWidget(btn); return w

    def _rebuild_tabs(self):
        ci = self.tab_widget.currentIndex()
        cur_id = self._tabs[ci]["id"] if 0 <= ci < len(self._tabs) else 0
        while self.tab_widget.count()>0: self.tab_widget.removeTab(0)
        self._pkg_lists.clear()
        for tab in self._tabs:
            pl=PackageList(tab["id"],self._tabs); pl.item_selected.connect(self.item_selected.emit)
            pl.delete_requested.connect(self.delete_requested.emit); pl.reorder_requested.connect(self.reorder_requested.emit)
            pl.move_to_tab.connect(self.move_to_tab.emit); pl.rename_requested.connect(self.rename_requested.emit)
            self._pkg_lists.append(pl)
            sa=QScrollArea(); sa.setWidgetResizable(True); sa.setStyleSheet("border:none;background:#11111b;"); sa.setWidget(pl)
            idx=self.tab_widget.addTab(sa,tab["name"])
            if tab["id"]!=0:
                cb=QPushButton("✕"); cb.setObjectName(_ON_BTN_DEL); cb.setFixedSize(16,16)
                # Direct connection — no lambda capture issue
                def _make_remover(tid):
                    def _rm(): self._remove_tab(tid)
                    return _rm
                cb.clicked.connect(_make_remover(tab["id"]))
                self.tab_widget.tabBar().setTabButton(idx,self.tab_widget.tabBar().ButtonPosition.RightSide,cb)
        for i,t in enumerate(self._tabs):
            if t["id"]==cur_id: self.tab_widget.setCurrentIndex(i); break

    def _on_sort(self,mode):
        self._sort_mode=SORT_NONE if self._sort_mode==mode else mode
        for i,m in enumerate([SORT_COMPLETION,SORT_TRIES,SORT_RIGHT]): self._sort_btns[i].setChecked(self._sort_mode==m)
        self.rebuild(self._datasets)
    def _add_tab(self):
        name,ok=QInputDialog.getText(self,"Новая вкладка","Название:")
        if ok and name.strip(): self._tabs.append({"id":self._next_id,"name":name.strip()}); self._next_id+=1; save_tabs(self._tabs); self._rebuild_tabs(); self.rebuild(self._datasets); self.tab_widget.setCurrentIndex(len(self._tabs)-1)
    def _remove_tab(self,tab_id):
        for ds in self._datasets:
            if ds.get("tab_id",0)==tab_id: ds["tab_id"]=0
        self._tabs=[t for t in self._tabs if t["id"]!=tab_id]; save_tabs(self._tabs); save_datasets(self._datasets); self._rebuild_tabs(); self.rebuild(self._datasets)
    def _rename_tab(self,index):
        if index<0 or index>=len(self._tabs) or self._tabs[index]["id"]==0: return
        name,ok=QInputDialog.getText(self,"Переименовать","Название:",text=self._tabs[index]["name"])
        if ok and name.strip(): self._tabs[index]["name"]=name.strip(); self.tab_widget.setTabText(index,name.strip()); save_tabs(self._tabs)
    def rebuild(self,datasets):
        self._datasets=datasets
        for pl in self._pkg_lists: pl.rebuild(datasets,self._sort_mode,self._tabs)
    def current_real_idx(self):
        idx=self.tab_widget.currentIndex()
        return self._pkg_lists[idx].current_real_idx() if 0<=idx<len(self._pkg_lists) else -1
    def select_by_real(self,real_idx):
        for pl in self._pkg_lists: pl.select_by_real(real_idx)
    def current_tab_id(self):
        idx=self.tab_widget.currentIndex(); return self._tabs[idx]["id"] if 0<=idx<len(self._tabs) else 0

__all__ = [
    'PackageList',
    'Sidebar',
]
