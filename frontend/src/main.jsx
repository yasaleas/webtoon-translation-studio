import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  AlignCenter,
  Bold,
  BoxSelect,
  ChevronRight,
  Eraser,
  FileImage,
  Languages,
  MousePointer2,
  Plus,
  RefreshCcw,
  Save,
  ScanText,
  Search,
  Settings,
  SlidersHorizontal,
  Trash2,
  WandSparkles,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { api } from "./lib/api";
import "./styles/app.css";

const emptySession = { projectId: "", episodeId: "" };
const FONT_SIZE_OPTIONS = [18, 22, 24, 28, 32, 36, 42, 48, 56, 64];
const GEMINI_MODEL_OPTIONS = [
  ["gemini-2.5-flash", "Gemini 2.5 Flash"],
  ["gemini-2.5-pro", "Gemini 2.5 Pro"],
  ["gemini-2.0-flash", "Gemini 2.0 Flash"],
  ["gemini-1.5-flash", "Gemini 1.5 Flash"],
];
const TARGET_LANGUAGE_OPTIONS = [
  ["TR", "Türkçe"],
  ["EN", "İngilizce"],
  ["KO", "Korece"],
  ["JA", "Japonca"],
  ["DE", "Almanca"],
  ["FR", "Fransızca"],
];
const OCR_LANGUAGE_OPTIONS = [
  ["en", "İngilizce"],
  ["korean", "Korece"],
  ["japan", "Japonca"],
  ["ch", "Çince"],
  ["tr", "Türkçe"],
];
const DETECT_LABEL_OPTIONS = [
  ["text_bubble,text_free", "Sadece yazı alanları"],
  ["text_free", "Balonsuz yazılar"],
  ["text_bubble", "Balon içi yazılar"],
  ["bubble,text_bubble,text_free", "Balon + yazı"],
];
const INPAINT_MODEL_OPTIONS = [
  ["lama", "LaMa"],
  ["mat", "MAT"],
  ["manga", "Manga"],
];
const DEVICE_OPTIONS = [
  ["cpu", "CPU"],
  ["cuda", "CUDA"],
];
const PAGE_SPLIT_OPTIONS = [
  [1, "Tek istek"],
  [2, "2 parça"],
  [3, "3 parça"],
  [4, "4 parça"],
  [5, "5 parça"],
  [6, "6 parça"],
  [8, "8 parça"],
];
const TIMEOUT_OPTIONS = [30, 45, 60, 90, 120];

function App() {
  const [projects, setProjects] = useState([]);
  const [episodes, setEpisodes] = useState([]);
  const [session, setSession] = useState(emptySession);
  const [pages, setPages] = useState([]);
  const [boxes, setBoxes] = useState([]);
  const [activePageId, setActivePageId] = useState("");
  const [activeBoxId, setActiveBoxId] = useState("");
  const [tool, setTool] = useState("select");
  const [zoom, setZoom] = useState(0.62);
  const [jobs, setJobs] = useState([]);
  const [fonts, setFonts] = useState([]);
  const [defaultFont, setDefaultFont] = useState("");
  const [defaultFontSize, setDefaultFontSize] = useState(28);
  const [targetLanguage, setTargetLanguage] = useState("TR");
  const [notice, setNotice] = useState("");
  const [imageVersion, setImageVersion] = useState(0);
  const [scrollTarget, setScrollTarget] = useState(null);
  const [settings, setSettings] = useState(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [warpEditBoxId, setWarpEditBoxId] = useState("");

  useEffect(() => {
    api.projects().then(setProjects).catch((error) => setNotice(error.message));
    api.settings().then((data) => {
      setSettings(data);
      if (data.editor?.defaultFontFamily) setDefaultFont(data.editor.defaultFontFamily);
      if (data.editor?.defaultFontSize) setDefaultFontSize(Number(data.editor.defaultFontSize));
      if (data.ai?.defaultTargetLanguage) setTargetLanguage(data.ai.defaultTargetLanguage.toUpperCase());
    }).catch((error) => setNotice(error.message));
    api.fonts().then((items) => {
      setFonts(items);
      setDefaultFont((current) => current || items.find((font) => font.id === "tight-spot-bb")?.id || items[0]?.id || "noto-sans");
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!fonts.length) return;
    const style = document.createElement("style");
    style.dataset.webtoonFonts = "true";
    style.textContent = fonts
      .map((font) => `@font-face{font-family:"${font.cssFamily}";src:url("${api.fontUrl(font.id)}") format("truetype");font-weight:400;font-style:normal;font-display:swap;}`)
      .join("\n");
    document.head.querySelectorAll("style[data-webtoon-fonts='true']").forEach((node) => node.remove());
    document.head.appendChild(style);
    return () => style.remove();
  }, [fonts]);

  useEffect(() => {
    if (!session.projectId) return;
    api.episodes(session.projectId).then(setEpisodes).catch((error) => setNotice(error.message));
  }, [session.projectId]);

  useEffect(() => {
    const timer = setInterval(() => api.jobs().then(setJobs).catch(() => {}), 1800);
    return () => clearInterval(timer);
  }, []);

  const activePage = useMemo(
    () => pages.find((page) => page.id === activePageId) || pages[0],
    [pages, activePageId],
  );
  const orderedBoxes = useMemo(() => orderBoxesByReadingPosition(boxes, pages), [boxes, pages]);
  const activeBox = boxes.find((box) => box.id === activeBoxId) || orderedBoxes[0];

  async function openSession(projectId = session.projectId, episodeId = session.episodeId) {
    if (!projectId || !episodeId) return;
    const data = await api.openSession(projectId, episodeId);
    const ordered = orderBoxesByReadingPosition(data.state.boxes || [], data.pages);
    setSession({ projectId, episodeId });
    setPages(data.pages);
    setBoxes(ordered);
    setActivePageId(data.pages[0]?.id || "");
    setActiveBoxId(ordered[0]?.id || "");
    setNotice("");
  }

  async function refreshState() {
    if (!session.projectId || !session.episodeId) return;
    const data = await api.openSession(session.projectId, session.episodeId);
    const ordered = orderBoxesByReadingPosition(data.state.boxes || [], data.pages);
    setPages(data.pages);
    setBoxes(ordered);
    setJobs(await api.jobs());
    return { pages: data.pages, boxes: ordered };
  }

  async function runJob(type, extra = {}) {
    if (!session.projectId || !session.episodeId) return;
    const result = await api.runJob(type, session, extra);
    setJobs((items) => [result, ...items.filter((item) => item.id !== result.id)]);
    if (["inpaint", "save"].includes(type)) {
      setImageVersion(Date.now());
    }
    await refreshState();
  }

  async function createBox(pageId, bbox) {
    const box = await api.createBox(session, pageId, bbox, { fontFamily: defaultFont || "tight-spot-bb", fontSize: defaultFontSize || 28 });
    await refreshState();
    setActivePageId(pageId);
    setActiveBoxId(box.id);
    setTool("select");
  }

  async function patchBox(boxId, patch) {
    setBoxes((items) => orderBoxesByReadingPosition(items.map((item) => (item.id === boxId ? { ...item, ...patch } : item)), pages));
    try {
      const updated = await api.updateBox(session, boxId, patch);
      setBoxes((items) => orderBoxesByReadingPosition(items.map((item) => (item.id === boxId ? updated : item)), pages));
      return updated;
    } catch (error) {
      setNotice(error.message);
      await refreshState();
      throw error;
    }
  }

  async function removeBox(boxId) {
    await api.deleteBox(session, boxId);
    setBoxes((items) => orderBoxesByReadingPosition(items.filter((item) => item.id !== boxId), pages));
    setActiveBoxId("");
  }

  async function restoreBox(boxId) {
    const updated = await api.restoreBox(session, boxId);
    setBoxes((items) => items.map((item) => (item.id === boxId ? updated : item)));
    setImageVersion(Date.now());
    setActiveBoxId(boxId);
    setNotice("");
  }

  async function toggleWarpEdit(box) {
    if (!box) return;
    if (warpEditBoxId === box.id) {
      setWarpEditBoxId("");
      return;
    }
    if (!box.corners) {
      await patchBox(box.id, { corners: resolvedBoxCorners(box) });
    }
    setWarpEditBoxId(box.id);
    setTool("select");
  }

  async function applyStyleToCurrentBoxes(stylePatch, boxIds = null) {
    if (!session.projectId || !session.episodeId || Object.keys(stylePatch).length === 0) return;
    await api.applyStyle(session, stylePatch, boxIds);
    await refreshState();
  }

  async function saveSettings(nextSettings) {
    const previousEditor = settings?.editor || {};
    const saved = await api.saveSettings(nextSettings);
    setSettings(saved);
    if (saved.editor?.defaultFontFamily) setDefaultFont(saved.editor.defaultFontFamily);
    if (saved.editor?.defaultFontSize) setDefaultFontSize(Number(saved.editor.defaultFontSize));
    if (saved.ai?.defaultTargetLanguage) setTargetLanguage(saved.ai.defaultTargetLanguage.toUpperCase());
    const stylePatch = {};
    if (saved.editor?.defaultFontFamily && saved.editor.defaultFontFamily !== previousEditor.defaultFontFamily) {
      stylePatch.fontFamily = saved.editor.defaultFontFamily;
    }
    const savedFontSize = Number(saved.editor?.defaultFontSize);
    const previousFontSize = Number(previousEditor.defaultFontSize || defaultFontSize || 28);
    if (Number.isFinite(savedFontSize) && savedFontSize !== previousFontSize) {
      stylePatch.fontSize = savedFontSize;
    }
    if (Object.keys(stylePatch).length > 0) {
      await applyStyleToCurrentBoxes(stylePatch);
    }
    setSettingsOpen(false);
    setNotice("Ayarlar kaydedildi.");
  }

  async function uploadFont(file, name) {
    const uploaded = await api.uploadFont(file, name);
    const items = await api.fonts();
    setFonts(items);
    setDefaultFont(uploaded.id);
    setSettings((current) => ({
      ...(current || {}),
      editor: { ...(current?.editor || {}), defaultFontFamily: uploaded.id },
    }));
    return uploaded;
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">WE</span>
          <div>
            <strong>Webtoon Editor</strong>
            <small>Yerel çeviri ve düzenleme stüdyosu</small>
          </div>
        </div>
        <div className="toolbar">
          <ToolButton active={tool === "select"} icon={MousePointer2} label="Seç" onClick={() => setTool("select")} />
          <ToolButton active={tool === "box"} icon={BoxSelect} label="Yazı alanı çiz" onClick={() => setTool("box")} />
          <ToolButton icon={ZoomOut} label="Uzaklaş" onClick={() => setZoom((value) => Math.max(0.3, value - 0.08))} />
          <span className="zoom-label">{Math.round(zoom * 100)}%</span>
          <ToolButton icon={ZoomIn} label="Yakınlaş" onClick={() => setZoom((value) => Math.min(1.4, value + 0.08))} />
        </div>
        <div className="top-actions">
          <ToolButton icon={Settings} label="Ayarlar" onClick={() => setSettingsOpen(true)} />
          <button className="primary-action" onClick={() => runJob("save")}>
            <Save size={17} /> Kaydet
          </button>
        </div>
      </header>

      <main className="workspace">
        <ProjectSidebar
          projects={projects}
          episodes={episodes}
          session={session}
          pages={pages}
          activePageId={activePage?.id}
          onProject={(projectId) => setSession({ projectId, episodeId: "" })}
          onEpisode={(episodeId) => {
            const next = { ...session, episodeId };
            setSession(next);
            openSession(next.projectId, next.episodeId).catch((error) => setNotice(error.message));
          }}
          onPage={(pageId) => {
            setActivePageId(pageId);
            setScrollTarget({ type: "page", pageId, nonce: Date.now() });
          }}
        />

        <section className="editor-stage">
          <ActionBar
            targetLanguage={targetLanguage}
            setTargetLanguage={setTargetLanguage}
            fonts={fonts}
            defaultFont={defaultFont}
            onDefaultFontChange={async (fontId) => {
              setDefaultFont(fontId);
              setSettings((current) => ({
                ...(current || {}),
                editor: { ...(current?.editor || {}), defaultFontFamily: fontId },
              }));
              try {
                await api.saveSettings({ editor: { defaultFontFamily: fontId } });
                await applyStyleToCurrentBoxes({ fontFamily: fontId });
              } catch (error) {
                setNotice(error.message);
              }
            }}
            runJob={runJob}
            refreshState={refreshState}
          />
          {notice ? <div className="notice">{notice}</div> : null}
          {activePage ? (
            <WebtoonReader
              session={session}
              pages={pages}
              boxes={boxes}
              activePageId={activePage.id}
              activeBoxId={activeBoxId}
              tool={tool}
              zoom={zoom}
              imageVersion={imageVersion}
              scrollTarget={scrollTarget}
              warpEditBoxId={warpEditBoxId}
              onCreateBox={createBox}
              onSelectPage={setActivePageId}
              onSelectBox={(boxId, pageId) => {
                setActivePageId(pageId);
                setActiveBoxId(boxId);
                setWarpEditBoxId((current) => (current && current !== boxId ? "" : current));
                setScrollTarget({ type: "inspector", boxId, nonce: Date.now() });
              }}
              onPatchBox={patchBox}
              fonts={fonts}
            />
          ) : (
            <EmptyState />
          )}
        </section>

        <Inspector
          box={activeBox}
          boxes={orderedBoxes}
          pages={pages}
          jobs={jobs}
          fonts={fonts}
          scrollTarget={scrollTarget}
          onSelect={(boxId) => {
            const selected = boxes.find((item) => item.id === boxId);
            if (selected) setActivePageId(selected.pageId);
            setActiveBoxId(boxId);
            setWarpEditBoxId((current) => (current && current !== boxId ? "" : current));
            setScrollTarget({ type: "canvas", boxId, pageId: selected?.pageId, nonce: Date.now() });
          }}
          onPatch={patchBox}
          onDelete={removeBox}
          onSingleOcr={(box) => runJob("ocr", { boxIds: [box.id] })}
          onSingleInpaint={(box) => runJob("inpaint", { boxIds: [box.id] })}
          onSinglePlace={(box) => runJob("place", { boxIds: [box.id] })}
          onSingleUnplace={(box) => runJob("unplace", { boxIds: [box.id] })}
          onRestoreOriginal={(box) => restoreBox(box.id).catch((error) => setNotice(error.message))}
          warpEditBoxId={warpEditBoxId}
          onToggleWarpEdit={toggleWarpEdit}
        />
      </main>
      {settingsOpen ? (
        <SettingsModal
          settings={settings}
          fonts={fonts}
          onClose={() => setSettingsOpen(false)}
          onSave={saveSettings}
          onUploadFont={(file, name) => uploadFont(file, name)}
        />
      ) : null}
    </div>
  );
}

function ProjectSidebar({ projects, episodes, session, pages, activePageId, onProject, onEpisode, onPage }) {
  return (
    <aside className="sidebar">
      <div className="panel-title">Projeler</div>
      <select value={session.projectId} onChange={(event) => onProject(event.target.value)}>
        <option value="">Proje seç</option>
        {projects.map((project) => (
          <option key={project.id} value={project.id}>
            {project.name}
          </option>
        ))}
      </select>
      <select value={session.episodeId} onChange={(event) => onEpisode(event.target.value)} disabled={!session.projectId}>
        <option value="">Bölüm seç</option>
        {episodes.map((episode) => (
          <option key={episode.id} value={episode.id}>
            {episode.name}
          </option>
        ))}
      </select>

      <div className="panel-title with-gap">Sayfalar</div>
      <div className="page-list">
        {pages.map((page, index) => (
          <button key={page.id} className={page.id === activePageId ? "page-row active" : "page-row"} onClick={() => onPage(page.id)}>
            <FileImage size={16} />
            <span>{index + 1}. {page.name}</span>
            <ChevronRight size={15} />
          </button>
        ))}
      </div>
    </aside>
  );
}

function ActionBar({ targetLanguage, setTargetLanguage, fonts, defaultFont, onDefaultFontChange, runJob, refreshState }) {
  return (
    <div className="actionbar">
      <button onClick={() => runJob("detect")}><WandSparkles size={16} /> Yazıları seç</button>
      <button onClick={() => runJob("ocr")}><ScanText size={16} /> OCR</button>
      <button onClick={() => runJob("inpaint")}><Eraser size={16} /> Sil</button>
      <div className="language-control">
        <Languages size={16} />
        <input value={targetLanguage} onChange={(event) => setTargetLanguage(event.target.value.toUpperCase())} />
      </div>
      <select className="font-control" value={defaultFont || fonts[0]?.id || ""} onChange={(event) => onDefaultFontChange(event.target.value)}>
        {fonts.map((font) => (
          <option key={font.id} value={font.id}>{font.name}</option>
        ))}
      </select>
      <button onClick={() => runJob("translate", { targetLanguage })}><Languages size={16} /> Çevir</button>
      <button onClick={() => runJob("place")}><AlignCenter size={16} /> Yerleştir</button>
      <button onClick={() => runJob("unplace")}><X size={16} /> Yerleşimi kaldır</button>
      <button className="ghost" onClick={refreshState}><RefreshCcw size={16} /> Yenile</button>
    </div>
  );
}

function WebtoonReader({
  session,
  pages,
  boxes,
  activePageId,
  activeBoxId,
  tool,
  zoom,
  imageVersion,
  scrollTarget,
  warpEditBoxId,
  onCreateBox,
  onSelectPage,
  onSelectBox,
  onPatchBox,
  fonts,
}) {
  const pageRefs = useRef({});
  const boxRefs = useRef({});

  useEffect(() => {
    if (!scrollTarget) return;
    if (scrollTarget.type === "page") {
      pageRefs.current[scrollTarget.pageId]?.scrollIntoView({ block: "start", behavior: "smooth" });
    }
    if (scrollTarget.type === "canvas") {
      boxRefs.current[scrollTarget.boxId]?.scrollIntoView({ block: "center", inline: "center", behavior: "smooth" });
    }
  }, [scrollTarget]);

  return (
    <div className="canvas-scroll">
      <div className="webtoon-reader">
        {pages.map((page, index) => (
          <PageCanvas
            key={page.id}
            refCallback={(node) => {
              pageRefs.current[page.id] = node;
            }}
            session={session}
            page={page}
            pageIndex={index}
            boxes={orderBoxesByReadingPosition(boxes.filter((box) => box.pageId === page.id), [page])}
            active={activePageId === page.id}
            activeBoxId={activeBoxId}
            tool={tool}
            zoom={zoom}
            imageVersion={imageVersion}
            warpEditBoxId={warpEditBoxId}
            registerBox={(boxId, node) => {
              if (node) boxRefs.current[boxId] = node;
              else delete boxRefs.current[boxId];
            }}
            onCreateBox={onCreateBox}
            onSelectPage={onSelectPage}
            onSelectBox={onSelectBox}
            onPatchBox={onPatchBox}
            fonts={fonts}
          />
        ))}
      </div>
    </div>
  );
}

function PageCanvas({
  refCallback,
  session,
  page,
  pageIndex,
  boxes,
  active,
  activeBoxId,
  tool,
  zoom,
  imageVersion,
  warpEditBoxId,
  registerBox,
  onCreateBox,
  onSelectPage,
  onSelectBox,
  onPatchBox,
  fonts,
}) {
  const stageRef = useRef(null);
  const [draft, setDraft] = useState(null);
  const [drag, setDrag] = useState(null);
  const [warpDrag, setWarpDrag] = useState(null);
  const imageSrc = `${api.imageUrl(session.projectId, session.episodeId, page.id)}&v=${imageVersion}`;

  function point(event) {
    const rect = stageRef.current.getBoundingClientRect();
    return {
      x: (event.clientX - rect.left) / zoom,
      y: (event.clientY - rect.top) / zoom,
    };
  }

  function onPointerDown(event) {
    onSelectPage(page.id);
    if (tool !== "box") return;
    const start = point(event);
    setDraft({ x: start.x, y: start.y, w: 1, h: 1, start });
  }

  function onPointerMove(event) {
    if (draft) {
      const current = point(event);
      setDraft({
        ...draft,
        x: Math.min(draft.start.x, current.x),
        y: Math.min(draft.start.y, current.y),
        w: Math.abs(current.x - draft.start.x),
        h: Math.abs(current.y - draft.start.y),
      });
    }
    if (drag) {
      const current = point(event);
      const dx = current.x - drag.start.x;
      const dy = current.y - drag.start.y;
      onPatchBox(drag.box.id, {
        bbox: { ...drag.box.bbox, x: Math.max(0, drag.origin.x + dx), y: Math.max(0, drag.origin.y + dy) },
      });
    }
    if (warpDrag) {
      const current = point(event);
      const box = warpDrag.box;
      const nextCorners = {
        ...defaultWarpCorners(),
        ...resolvedBoxCorners(box),
        [warpDrag.corner]: {
          x: roundWarp(clamp((current.x - box.bbox.x) / box.bbox.w, -1, 2)),
          y: roundWarp(clamp((current.y - box.bbox.y) / box.bbox.h, -1, 2)),
        },
      };
      onPatchBox(box.id, { corners: nextCorners });
    }
  }

  function onPointerUp() {
    if (draft && draft.w > 18 && draft.h > 18) onCreateBox(page.id, { x: draft.x, y: draft.y, w: draft.w, h: draft.h });
    setDraft(null);
    setDrag(null);
    setWarpDrag(null);
  }

  return (
    <section className={active ? "reader-page active" : "reader-page"} ref={refCallback}>
      <div className="reader-page-title">
        <span>{pageIndex + 1}</span>
        <strong>{page.name}</strong>
        <em>{boxes.length} yazı</em>
      </div>
      <div
        ref={stageRef}
        className={`canvas-page tool-${tool}`}
        style={{ width: page.width * zoom, height: page.height * zoom }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
      >
        <img src={imageSrc} alt={page.name} style={{ width: page.width * zoom, height: page.height * zoom }} draggable="false" />
        <div className="overlay" style={{ transform: `scale(${zoom})`, width: page.width, height: page.height }}>
          {boxes.map((box) => (
            <div
              key={box.id}
              ref={(node) => registerBox(box.id, node)}
              className={box.id === activeBoxId ? "box active" : "box"}
              style={{ left: box.bbox.x, top: box.bbox.y, width: box.bbox.w, height: box.bbox.h }}
              onPointerDown={(event) => {
                if (tool !== "select") return;
                event.stopPropagation();
                onSelectPage(page.id);
                onSelectBox(box.id, page.id);
                if (warpEditBoxId === box.id) return;
                setDrag({ box, start: point(event), origin: { x: box.bbox.x, y: box.bbox.y } });
              }}
            >
              {hasCustomWarp(resolvedBoxCorners(box)) && warpEditBoxId !== box.id ? <SelectionShape box={box} /> : null}
              {box.translatedText && box.status === "placed" ? <TextPreview box={box} fonts={fonts} /> : null}
              {warpEditBoxId === box.id ? (
                <WarpControls
                  box={box}
                  onCornerDown={(event, corner) => {
                    event.stopPropagation();
                    onSelectPage(page.id);
                    onSelectBox(box.id, page.id);
                    setWarpDrag({ box, corner });
                  }}
                />
              ) : null}
              <span>{box.order}</span>
              <i>{box.status}</i>
            </div>
          ))}
          {draft ? <div className="box draft" style={{ left: draft.x, top: draft.y, width: draft.w, height: draft.h }} /> : null}
        </div>
      </div>
    </section>
  );
}

function TextPreview({ box, fonts }) {
  const style = box.style || {};
  const font = fonts.find((item) => item.id === style.fontFamily) || fonts[0];
  const warpTransform = textWarpTransform(box);
  const hasWarp = Boolean(warpTransform);
  return (
    <div
      className="text-preview"
      style={{
        inset: hasWarp ? "auto" : "4px",
        left: hasWarp ? 0 : undefined,
        top: hasWarp ? 0 : undefined,
        width: hasWarp ? box.bbox.w : undefined,
        height: hasWarp ? box.bbox.h : undefined,
        color: style.color || "#111111",
        WebkitTextStroke: `${style.strokeWidth || 1}px ${style.strokeColor || "#ffffff"}`,
        fontSize: `${style.fontSize || 28}px`,
        fontWeight: style.bold ? 800 : 700,
        lineHeight: style.lineHeight || 1.1,
        fontFamily: font ? `"${font.cssFamily}", "Noto Sans", sans-serif` : undefined,
        transform: hasWarp ? `${warpTransform} ${textTransformStyle(style)}` : textTransformStyle(style),
        transformOrigin: hasWarp ? "0 0" : "center",
      }}
    >
      {box.translatedText}
    </div>
  );
}

function WarpControls({ box, onCornerDown }) {
  const corners = resolvedBoxCorners(box);
  const points = warpPoints(corners, box.bbox);
  return (
    <div className="warp-layer">
      <svg className="warp-outline" viewBox={`0 0 ${box.bbox.w} ${box.bbox.h}`} preserveAspectRatio="none">
        <polygon points={points.map((point) => `${point.x},${point.y}`).join(" ")} />
      </svg>
      {Object.entries(pointsByCorner(corners, box.bbox)).map(([corner, point]) => (
        <button
          key={corner}
          type="button"
          className={`warp-corner ${corner}`}
          style={{ left: point.x, top: point.y }}
          onPointerDown={(event) => onCornerDown(event, corner)}
          title="Köşeyi sürükle"
        />
      ))}
    </div>
  );
}

function SelectionShape({ box }) {
  const corners = resolvedBoxCorners(box);
  const points = warpPoints(corners, box.bbox);
  return (
    <svg className="shape-outline" viewBox={`0 0 ${box.bbox.w} ${box.bbox.h}`} preserveAspectRatio="none">
      <polygon points={points.map((point) => `${point.x},${point.y}`).join(" ")} />
    </svg>
  );
}

function Inspector({
  box,
  boxes,
  pages,
  jobs,
  fonts,
  scrollTarget,
  onSelect,
  onPatch,
  onDelete,
  onSingleOcr,
  onSingleInpaint,
  onSinglePlace,
  onSingleUnplace,
  onRestoreOriginal,
  warpEditBoxId,
  onToggleWarpEdit,
}) {
  const rowRefs = useRef({});
  const style = box?.style || {};

  useEffect(() => {
    if (scrollTarget?.type === "inspector") {
      rowRefs.current[scrollTarget.boxId]?.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [scrollTarget]);

  return (
    <aside className="inspector">
      <div className="panel-title">Yazı Akışı</div>
      <div className="box-list">
        {boxes.map((item) => (
          <button
            key={item.id}
            ref={(node) => {
              if (node) rowRefs.current[item.id] = node;
              else delete rowRefs.current[item.id];
            }}
            className={item.id === box?.id ? "box-row active" : "box-row"}
            onClick={() => onSelect(item.id)}
          >
            <span>{boxLabel(item, pages)}</span>
            <strong>{item.translatedText || item.sourceText || "Metin bekliyor"}</strong>
            <em>{item.status}</em>
          </button>
        ))}
      </div>

      {box ? (
        <div className="detail">
          <div className="detail-head">
            <h2>{boxLabel(box, pages)} Düzenle</h2>
            <button className="icon-danger" onClick={() => onDelete(box.id)}><Trash2 size={16} /></button>
          </div>
          <label>Orijinal metin</label>
          <textarea value={box.sourceText} onChange={(event) => onPatch(box.id, { sourceText: event.target.value })} />
          <label>Çeviri</label>
          <textarea value={box.translatedText} onChange={(event) => onPatch(box.id, { translatedText: event.target.value })} />
          <div className="inline-tools">
            <button onClick={() => onSingleOcr(box)}><Search size={15} /> OCR</button>
            <button onClick={() => onSingleInpaint(box)}><Eraser size={15} /> Sil</button>
            <button onClick={() => onSinglePlace(box)}><AlignCenter size={15} /> Yerleştir</button>
            <button onClick={() => onSingleUnplace(box)}><X size={15} /> Kaldır</button>
            <button onClick={() => onRestoreOriginal(box)}><RefreshCcw size={15} /> Orijinale dön</button>
          </div>
          <div className="style-grid">
            <label className="wide">Font<select value={style.fontFamily || "tight-spot-bb"} onChange={(event) => onPatch(box.id, { style: { ...style, fontFamily: event.target.value } })}>
              {fonts.map((font) => (
                <option key={font.id} value={font.id}>{font.name}</option>
              ))}
            </select></label>
            <label>Boyut<input type="number" value={style.fontSize || 28} onChange={(event) => onPatch(box.id, { style: { ...style, fontSize: Number(event.target.value) } })} /></label>
            <label>Renk<input type="color" value={style.color || "#111111"} onChange={(event) => onPatch(box.id, { style: { ...style, color: event.target.value } })} /></label>
            <label>Kontur<input type="color" value={style.strokeColor || "#ffffff"} onChange={(event) => onPatch(box.id, { style: { ...style, strokeColor: event.target.value } })} /></label>
            <button className="toggle" onClick={() => onPatch(box.id, { style: { ...style, bold: !style.bold } })}><Bold size={15} /> Kalın</button>
            <label>Genişlik <span>{Number(style.scaleX || 1).toFixed(2)}x</span><input type="range" min="0.5" max="2.5" step="0.05" value={style.scaleX || 1} onChange={(event) => onPatch(box.id, { style: { ...style, scaleX: Number(event.target.value) } })} /></label>
            <label>Döndür <span>{style.rotation || 0}°</span><input type="range" min="-45" max="45" step="1" value={style.rotation || 0} onChange={(event) => onPatch(box.id, { style: { ...style, rotation: Number(event.target.value) } })} /></label>
            <label>Perspektif X <span>{style.perspectiveX || 0}</span><input type="range" min="-70" max="70" step="1" value={style.perspectiveX || 0} onChange={(event) => onPatch(box.id, { style: { ...style, perspectiveX: Number(event.target.value) } })} /></label>
            <label>Perspektif Y <span>{style.perspectiveY || 0}</span><input type="range" min="-70" max="70" step="1" value={style.perspectiveY || 0} onChange={(event) => onPatch(box.id, { style: { ...style, perspectiveY: Number(event.target.value) } })} /></label>
            <label>Eğiklik <span>{style.skewX || 0}°</span><input type="range" min="-45" max="45" step="1" value={style.skewX || 0} onChange={(event) => onPatch(box.id, { style: { ...style, skewX: Number(event.target.value) } })} /></label>
            <button className={warpEditBoxId === box.id ? "toggle wide-button active" : "toggle wide-button"} onClick={() => onToggleWarpEdit(box)}><SlidersHorizontal size={15} /> Köşe modu</button>
            <button className="toggle wide-button" onClick={() => onPatch(box.id, { corners: defaultWarpCorners(), style: { ...style, scaleX: 1, rotation: 0, perspectiveX: 0, perspectiveY: 0, skewX: 0 } })}><SlidersHorizontal size={15} /> Perspektifi sıfırla</button>
          </div>
        </div>
      ) : null}

      <div className="panel-title with-gap">İş Kuyruğu</div>
      <div className="job-list">
        {jobs.length === 0 ? <p>Henüz işlem yok.</p> : null}
        {jobs.map((job) => (
          <div key={job.id} className={`job ${job.status}`}>
            <span>{job.type}</span>
            <strong>{job.message}</strong>
            <div><b style={{ width: `${job.progress}%` }} /></div>
          </div>
        ))}
      </div>
    </aside>
  );
}

function SettingsModal({ settings, fonts, onClose, onSave, onUploadFont }) {
  const [draft, setDraft] = useState(() => draftSettings(settings));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [fontFile, setFontFile] = useState(null);
  const [fontName, setFontName] = useState("");
  const [uploadingFont, setUploadingFont] = useState(false);
  const ai = draft.ai;
  const editor = draft.editor;

  useEffect(() => {
    setDraft(draftSettings(settings));
  }, [settings]);

  function patchAi(patch) {
    setDraft((value) => ({ ...value, ai: { ...value.ai, ...patch } }));
  }

  function patchEditor(patch) {
    setDraft((value) => ({ ...value, editor: { ...value.editor, ...patch } }));
  }

  function updateGeminiKey(id, patch) {
    patchAi({
      geminiKeys: ai.geminiKeys.map((item) => (item.id === id ? { ...item, ...patch } : item)),
    });
  }

  function addGeminiKey() {
    const key = newGeminiKey();
    patchAi({
      geminiKeys: [...ai.geminiKeys, key],
      activeGeminiKeyId: ai.activeGeminiKeyId || key.id,
    });
  }

  function removeGeminiKey(id) {
    const keys = ai.geminiKeys.filter((item) => item.id !== id);
    patchAi({
      geminiKeys: keys,
      activeGeminiKeyId: ai.activeGeminiKeyId === id ? keys[0]?.id || "" : ai.activeGeminiKeyId,
    });
  }

  async function submit(event) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await onSave({
        editor,
        ai: {
          ...ai,
          defaultTargetLanguage: ai.defaultTargetLanguage.toUpperCase(),
          geminiKeys: ai.geminiKeys.map(({ id, name, apiKey, createdAt }) => ({ id, name, apiKey, createdAt })),
        },
      });
    } catch (saveError) {
      setError(saveError.message);
    } finally {
      setSaving(false);
    }
  }

  async function uploadSelectedFont() {
    if (!fontFile) return;
    setUploadingFont(true);
    setError("");
    try {
      const uploaded = await onUploadFont(fontFile, fontName);
      patchEditor({ defaultFontFamily: uploaded.id });
      setFontFile(null);
      setFontName("");
    } catch (uploadError) {
      setError(uploadError.message);
    } finally {
      setUploadingFont(false);
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <form className="settings-dialog" onSubmit={submit}>
        <div className="settings-head">
          <div>
            <h2>Ayarlar</h2>
            <span>Yapay zeka ve işlem ayarları</span>
          </div>
          <button type="button" className="tool" onClick={onClose} title="Kapat"><X size={18} /></button>
        </div>

        <div className="settings-body">
          <section className="settings-section">
            <h3>Yazı ve Font</h3>
            <div className="settings-grid">
              <label>Varsayılan font<select value={editor.defaultFontFamily} onChange={(event) => patchEditor({ defaultFontFamily: event.target.value })}>
                {fonts.map((font) => (
                  <option key={font.id} value={font.id}>{font.name}</option>
                ))}
              </select></label>
              <label>Varsayılan boyut<select value={editor.defaultFontSize} onChange={(event) => patchEditor({ defaultFontSize: Number(event.target.value) })}>
                {withCurrentOption(FONT_SIZE_OPTIONS, Number(editor.defaultFontSize)).map((size) => (
                  <option key={size} value={size}>{size}px</option>
                ))}
              </select></label>
              <label>Yüklenecek font adı<input value={fontName} onChange={(event) => setFontName(event.target.value)} placeholder="Örn. Anime Ace" /></label>
            </div>
            <div className="font-upload-row">
              <input type="file" accept=".ttf,.otf" onChange={(event) => setFontFile(event.target.files?.[0] || null)} />
              <button type="button" onClick={uploadSelectedFont} disabled={!fontFile || uploadingFont}>{uploadingFont ? "Yükleniyor" : "Font yükle"}</button>
            </div>
          </section>

          <section className="settings-section">
            <div className="settings-section-head">
              <h3>Gemini</h3>
              <button type="button" onClick={addGeminiKey}><Plus size={15} /> Key ekle</button>
            </div>
            <div className="key-list">
              <p>
                {ai.envGeminiKeyAvailable
                  ? ".env içindeki GEMINI_API_KEY aktif. Buradaki keyler sadece yerel yedek kullanım içindir."
                  : "Önerilen yöntem: proje kökünde .env dosyasına GEMINI_API_KEY eklemek. Buradan eklenen keyler sadece yerel data/settings.json içinde saklanır."}
              </p>
              {ai.geminiKeys.map((item) => (
                <div key={item.id} className="key-row">
                  <input
                    type="radio"
                    name="activeGeminiKey"
                    checked={ai.activeGeminiKeyId === item.id}
                    onChange={() => patchAi({ activeGeminiKeyId: item.id })}
                    title="Aktif"
                  />
                  <input value={item.name} onChange={(event) => updateGeminiKey(item.id, { name: event.target.value })} placeholder="İsim" />
                  <input
                    type="password"
                    value={item.apiKey || ""}
                    onChange={(event) => updateGeminiKey(item.id, { apiKey: event.target.value })}
                    placeholder={item.maskedKey || "API key"}
                    autoComplete="off"
                  />
                  <span>{item.maskedKey || "yeni"}</span>
                  <button type="button" className="icon-danger" onClick={() => removeGeminiKey(item.id)} title="Sil"><Trash2 size={15} /></button>
                </div>
              ))}
            </div>
            <div className="settings-grid">
              <label>Gemini model<SelectWithOptions value={ai.geminiModel} options={GEMINI_MODEL_OPTIONS} onChange={(value) => patchAi({ geminiModel: value })} /></label>
              <label>Varsayılan dil<SelectWithOptions value={ai.defaultTargetLanguage} options={TARGET_LANGUAGE_OPTIONS} onChange={(value) => patchAi({ defaultTargetLanguage: value.toUpperCase() })} /></label>
              <label>Bölüm parçalama<select value={ai.geminiPageSplits} onChange={(event) => patchAi({ geminiPageSplits: Number(event.target.value) })}>
                {withCurrentOption(PAGE_SPLIT_OPTIONS.map(([value]) => value), Number(ai.geminiPageSplits)).map((count) => (
                  <option key={count} value={count}>{PAGE_SPLIT_OPTIONS.find(([value]) => value === count)?.[1] || `${count} parça`}</option>
                ))}
              </select></label>
              <label>Zaman aşımı<select value={ai.geminiTimeout} onChange={(event) => patchAi({ geminiTimeout: Number(event.target.value) })}>
                {withCurrentOption(TIMEOUT_OPTIONS, Number(ai.geminiTimeout)).map((seconds) => (
                  <option key={seconds} value={seconds}>{seconds} sn</option>
                ))}
              </select></label>
            </div>
          </section>

          <section className="settings-section">
            <h3>Algılama ve OCR</h3>
            <div className="settings-grid">
              <label className="wide">RT-DETR model<SelectWithOptions value={ai.rtdetrModelId} options={[["ogkalu/comic-text-and-bubble-detector", "Comic text detector"]]} onChange={(value) => patchAi({ rtdetrModelId: value })} /></label>
              <label>Algılama modu<SelectWithOptions value={ai.rtdetrTextLabels} options={DETECT_LABEL_OPTIONS} onChange={(value) => patchAi({ rtdetrTextLabels: value })} /></label>
              <label>Eşik<input type="number" min="0.05" max="0.95" step="0.01" value={ai.rtdetrThreshold} onChange={(event) => patchAi({ rtdetrThreshold: Number(event.target.value) })} /></label>
              <label>OCR dili<SelectWithOptions value={ai.ocrLanguage} options={OCR_LANGUAGE_OPTIONS} onChange={(value) => patchAi({ ocrLanguage: value })} /></label>
              <label className="check-row"><input type="checkbox" checked={ai.strictMode} onChange={(event) => patchAi({ strictMode: event.target.checked })} /> Hataları durdur</label>
            </div>
          </section>

          <section className="settings-section">
            <h3>Temizleme</h3>
            <div className="settings-grid">
              <label>IOPaint model<SelectWithOptions value={ai.inpaintModel} options={INPAINT_MODEL_OPTIONS} onChange={(value) => patchAi({ inpaintModel: value })} /></label>
              <label>Cihaz<SelectWithOptions value={ai.aiDevice} options={DEVICE_OPTIONS} onChange={(value) => patchAi({ aiDevice: value })} /></label>
              <label>Maske payı<input type="number" min="0" max="80" value={ai.inpaintPadding} onChange={(event) => patchAi({ inpaintPadding: Number(event.target.value) })} /></label>
            </div>
          </section>
        </div>

        <div className="settings-footer">
          {error ? <span className="settings-error">{error}</span> : null}
          <button type="button" className="ghost" onClick={onClose}>Vazgeç</button>
          <button type="submit" className="primary-action" disabled={saving}>{saving ? "Kaydediliyor" : "Kaydet"}</button>
        </div>
      </form>
    </div>
  );
}

function SelectWithOptions({ value, options, onChange }) {
  const normalized = options.slice();
  if (value && !normalized.some(([optionValue]) => optionValue === value)) {
    normalized.push([value, value]);
  }
  return (
    <select value={value} onChange={(event) => onChange(event.target.value)}>
      {normalized.map(([optionValue, label]) => (
        <option key={optionValue} value={optionValue}>{label}</option>
      ))}
    </select>
  );
}

function textTransformStyle(style) {
  const scaleX = Number(style.scaleX || 1);
  const rotation = Number(style.rotation || 0);
  const skewX = Number(style.skewX || 0);
  const perspectiveX = Number(style.perspectiveX || 0);
  const perspectiveY = Number(style.perspectiveY || 0);
  return `perspective(520px) rotateY(${perspectiveX}deg) rotateX(${-perspectiveY}deg) skewX(${skewX}deg) rotate(${rotation}deg) scaleX(${scaleX})`;
}

function textWarpTransform(box) {
  const corners = resolvedBoxCorners(box);
  if (!hasCustomWarp(corners)) return "";
  const bbox = box.bbox || {};
  const width = Number(bbox?.w || 1);
  const height = Number(bbox?.h || 1);
  const source = [
    { x: 0, y: 0 },
    { x: width, y: 0 },
    { x: width, y: height },
    { x: 0, y: height },
  ];
  const destination = warpPoints(corners, bbox);
  const coefficients = projectiveCoefficients(source, destination);
  if (!coefficients) return "";
  const [a, b, c, d, e, f, g, h] = coefficients;
  const matrix = [a, d, 0, g, b, e, 0, h, 0, 0, 1, 0, c, f, 0, 1];
  return `matrix3d(${matrix.map((value) => Number(value.toFixed(8))).join(",")})`;
}

function projectiveCoefficients(source, destination) {
  const matrix = [];
  const vector = [];
  source.forEach((point, index) => {
    const target = destination[index];
    matrix.push([point.x, point.y, 1, 0, 0, 0, -target.x * point.x, -target.x * point.y]);
    matrix.push([0, 0, 0, point.x, point.y, 1, -target.y * point.x, -target.y * point.y]);
    vector.push(target.x, target.y);
  });
  return solveLinearSystem(matrix, vector);
}

function solveLinearSystem(matrix, vector) {
  const size = vector.length;
  const rows = matrix.map((row, index) => [...row, vector[index]]);
  for (let column = 0; column < size; column += 1) {
    let pivot = column;
    for (let row = column + 1; row < size; row += 1) {
      if (Math.abs(rows[row][column]) > Math.abs(rows[pivot][column])) pivot = row;
    }
    if (Math.abs(rows[pivot][column]) < 1e-9) return null;
    [rows[column], rows[pivot]] = [rows[pivot], rows[column]];
    const divisor = rows[column][column];
    for (let col = column; col <= size; col += 1) rows[column][col] /= divisor;
    for (let row = 0; row < size; row += 1) {
      if (row === column) continue;
      const factor = rows[row][column];
      for (let col = column; col <= size; col += 1) rows[row][col] -= factor * rows[column][col];
    }
  }
  return rows.map((row) => row[size]);
}

function defaultWarpCorners() {
  return {
    tl: { x: 0, y: 0 },
    tr: { x: 1, y: 0 },
    br: { x: 1, y: 1 },
    bl: { x: 0, y: 1 },
  };
}

function resolvedBoxCorners(box = {}) {
  const defaults = defaultWarpCorners();
  const incoming = box?.corners || box?.style?.warpCorners || {};
  return Object.fromEntries(
    Object.entries(defaults).map(([corner, point]) => [
      corner,
      {
        x: clamp(Number(incoming[corner]?.x ?? point.x), -1, 2),
        y: clamp(Number(incoming[corner]?.y ?? point.y), -1, 2),
      },
    ]),
  );
}

function pointsByCorner(corners, bbox) {
  const width = Number(bbox?.w || 1);
  const height = Number(bbox?.h || 1);
  return Object.fromEntries(
    Object.entries(corners).map(([corner, point]) => [
      corner,
      { x: point.x * width, y: point.y * height },
    ]),
  );
}

function warpPoints(corners, bbox) {
  const points = pointsByCorner(corners, bbox);
  return [points.tl, points.tr, points.br, points.bl];
}

function hasCustomWarp(corners) {
  const defaults = defaultWarpCorners();
  return Object.keys(defaults).some(
    (corner) => Math.abs(corners[corner].x - defaults[corner].x) > 0.001 || Math.abs(corners[corner].y - defaults[corner].y) > 0.001,
  );
}

function clamp(value, minimum, maximum) {
  return Math.min(Math.max(Number.isFinite(value) ? value : minimum, minimum), maximum);
}

function roundWarp(value) {
  return Math.round(value * 10000) / 10000;
}

function withCurrentOption(options, current) {
  if (!Number.isFinite(current) || options.includes(current)) return options;
  return [...options, current].sort((a, b) => a - b);
}

function boxLabel(box, pages) {
  const pageIndex = Math.max(0, pages.findIndex((page) => page.id === box.pageId));
  return `${pageIndex + 1}.${box.order}`;
}

function orderBoxesByReadingPosition(items, pages) {
  const sorted = items.slice().sort((a, b) => {
    const pageA = pageIndex(pages, a.pageId);
    const pageB = pageIndex(pages, b.pageId);
    if (pageA !== pageB) return pageA - pageB;
    const y = Number(a.bbox?.y || 0) - Number(b.bbox?.y || 0);
    if (y !== 0) return y;
    const x = Number(a.bbox?.x || 0) - Number(b.bbox?.x || 0);
    if (x !== 0) return x;
    return String(a.id).localeCompare(String(b.id));
  });
  const pageCounts = new Map();
  return sorted.map((box) => {
    const nextOrder = (pageCounts.get(box.pageId) || 0) + 1;
    pageCounts.set(box.pageId, nextOrder);
    return box.order === nextOrder ? box : { ...box, order: nextOrder };
  });
}

function pageIndex(pages, pageId) {
  const index = pages.findIndex((page) => page.id === pageId);
  return index === -1 ? Number.MAX_SAFE_INTEGER : index;
}

function draftSettings(settings) {
  const ai = settings?.ai || {};
  const editor = settings?.editor || {};
  return {
    editor: {
      defaultFontFamily: editor.defaultFontFamily || "noto-sans-black",
      defaultFontSize: editor.defaultFontSize || 28,
    },
    ai: {
      defaultTargetLanguage: ai.defaultTargetLanguage || "TR",
      geminiModel: ai.geminiModel || "gemini-2.5-flash",
      geminiPageSplits: ai.geminiPageSplits || 2,
      geminiBatchSize: ai.geminiBatchSize || 8,
      geminiBatchChars: ai.geminiBatchChars || 2200,
      geminiTimeout: ai.geminiTimeout || 60,
      activeGeminiKeyId: ai.activeGeminiKeyId || "",
      envGeminiKeyAvailable: Boolean(ai.envGeminiKeyAvailable),
      geminiKeys: (ai.geminiKeys || []).map((item) => ({ ...item, apiKey: "" })),
      rtdetrModelId: ai.rtdetrModelId || "ogkalu/comic-text-and-bubble-detector",
      rtdetrThreshold: ai.rtdetrThreshold ?? 0.55,
      rtdetrTextLabels: ai.rtdetrTextLabels || "text_bubble,text_free",
      ocrLanguage: ai.ocrLanguage || "en",
      inpaintModel: ai.inpaintModel || "lama",
      aiDevice: ai.aiDevice || "cpu",
      inpaintPadding: ai.inpaintPadding ?? 8,
      strictMode: Boolean(ai.strictMode),
    },
  };
}

function newGeminiKey() {
  const id = crypto.randomUUID ? crypto.randomUUID() : `key-${Date.now()}`;
  return { id, name: "Yeni Gemini Key", apiKey: "", maskedKey: "", createdAt: "" };
}

function ToolButton({ icon: Icon, label, active, onClick }) {
  return (
    <button className={active ? "tool active" : "tool"} onClick={onClick} title={label}>
      <Icon size={18} />
    </button>
  );
}

function EmptyState() {
  return (
    <div className="empty-state">
      <Plus size={30} />
      <h1>Bir proje ve bölüm seç</h1>
      <p>Görseller `data/projects/ProjeAdi/BolumAdi/Orjinal` içine yerleştirildiğinde burada düzenlenebilir.</p>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
