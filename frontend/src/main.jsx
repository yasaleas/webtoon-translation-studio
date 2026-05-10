import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  AlignCenter,
  Bold,
  BoxSelect,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Clock3,
  Eraser,
  FileImage,
  FolderOpen,
  Home,
  Languages,
  Layers3,
  MousePointer2,
  Paintbrush,
  Plus,
  RefreshCcw,
  Save,
  ScanText,
  Search,
  Settings,
  SlidersHorizontal,
  Trash2,
  Type,
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
  ["gemini-3-flash-preview", "Gemini 3 Flash"],
  ["gemini-3.1-flash-lite-preview", "Gemini 3.1 Flash Lite"],
  ["gemini-2.5-flash", "Gemini 2.5 Flash"],
  ["gemini-2.5-flash-lite", "Gemini 2.5 Flash Lite"],
  ["gemini-2.5-pro", "Gemini 2.5 Pro"],
  ["gemma-4-31b-it", "Gemma 4 31B"],
  ["gemma-4-26b-a4b-it", "Gemma 4 26B"],
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
  ["text_bubble,text_free", "Yazı kutuları"],
  ["text_free", "Balonsuz yazı"],
  ["text_bubble", "Balon içi yazı"],
  ["bubble,text_bubble,text_free", "Balon + yazı"],
];
const DETECTION_MODEL_CONFIGS = {
  "ogkalu/comic-text-and-bubble-detector": {
    label: "RT-DETR V2 text/bubble",
    note: "Girdi: tam sayfa RGB görsel. Çıktı: bubble, text_bubble, text_free sınıflı kutular ve skorlar.",
    output: "bubble / text_bubble / text_free",
    thresholdLabel: "Güven eşiği",
    defaultThreshold: 0.55,
    defaultLabels: "text_bubble,text_free",
    labelOptions: DETECT_LABEL_OPTIONS,
    showLabelMode: true,
    showMergeGap: false,
  },
  "ogkalu/comic-text-segmenter-yolov8m": {
    label: "YOLOv8m text segmenter",
    note: "Girdi: tam sayfa görsel. Çıktı: text_comic sınıfı, kutu ve varsa segmentasyon maskesi. Uzun webtoon oranlarına daha toleranslıdır.",
    output: "text_comic",
    thresholdLabel: "Güven eşiği",
    defaultThreshold: 0.55,
    defaultLabels: "text_comic",
    showLabelMode: false,
    showMergeGap: false,
  },
  "huyvux3005/manga109-segmentation-bubble": {
    label: "Manga109 bubble segmentation",
    note: "Girdi: tam sayfa görsel. Çıktı: balloon sınıfı ve segmentasyon maskesi. Yazıyı değil konuşma balonunu hedefler.",
    output: "balloon",
    thresholdLabel: "Güven eşiği",
    defaultThreshold: 0.55,
    defaultLabels: "balloon",
    showLabelMode: false,
    showMergeGap: false,
  },
  "a-b-c-x-y-z/Manga-Text-Segmentation-2025": {
    label: "Manga Text Segmentation 2025",
    note: "Girdi: tam sayfa RGB görsel. Çıktı: piksel düzeyinde metin olasılık maskesi; editör bu maskeyi kutulara çevirir.",
    output: "text mask",
    thresholdLabel: "Maske eşiği",
    defaultThreshold: 0.55,
    defaultLabels: "text",
    showLabelMode: false,
    showMergeGap: true,
  },
};
const DETECTION_MODEL_OPTIONS = Object.entries(DETECTION_MODEL_CONFIGS).map(([value, config]) => [value, config.label]);
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
  const [manualMasks, setManualMasks] = useState([]);
  const [activePageId, setActivePageId] = useState("");
  const [activeBoxId, setActiveBoxId] = useState("");
  const [selectedBoxIds, setSelectedBoxIds] = useState([]);
  const [tool, setTool] = useState("select");
  const [brushSize, setBrushSize] = useState(36);
  const [brushMode, setBrushMode] = useState("paint");
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
  const [view, setView] = useState("projects");
  const [warpEditBoxId, setWarpEditBoxId] = useState("");
  const [metadataBusyProjectId, setMetadataBusyProjectId] = useState("");
  const [metadataCandidates, setMetadataCandidates] = useState({ projectId: "", items: [], errors: [] });

  useEffect(() => {
    loadProjects().catch((error) => setNotice(error.message));
    api.settings().then((data) => {
      setSettings(data);
      if (data.editor?.defaultFontFamily) setDefaultFont(data.editor.defaultFontFamily);
      if (data.editor?.defaultFontSize) setDefaultFontSize(Number(data.editor.defaultFontSize));
      if (data.ai?.defaultTargetLanguage) setTargetLanguage(data.ai.defaultTargetLanguage.toUpperCase());
    }).catch((error) => setNotice(error.message));
    api.fonts().then((items) => {
      setFonts(items);
      setDefaultFont((current) => current || items.find((font) => font.id === "noto-sans-black")?.id || items[0]?.id || "noto-sans");
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
    const timer = setInterval(() => api.jobs().then(setJobs).catch(() => {}), 850);
    return () => clearInterval(timer);
  }, []);

  const activePage = useMemo(
    () => pages.find((page) => page.id === activePageId) || pages[0],
    [pages, activePageId],
  );
  const orderedBoxes = useMemo(() => orderBoxesByReadingPosition(boxes, pages), [boxes, pages]);
  const validSelectedBoxIds = useMemo(() => {
    const ids = new Set(boxes.map((box) => box.id));
    return selectedBoxIds.filter((id) => ids.has(id));
  }, [boxes, selectedBoxIds]);
  const activeBox = boxes.find((box) => box.id === activeBoxId) || boxes.find((box) => validSelectedBoxIds.includes(box.id)) || orderedBoxes[0];
  const activeProject = projects.find((project) => project.id === session.projectId);
  const activeEpisode = episodes.find((episode) => episode.id === session.episodeId);
  const sessionStats = useMemo(() => ({
    pages: pages.length,
    boxes: orderedBoxes.length,
    placed: orderedBoxes.filter((box) => box.status === "placed").length,
    translated: orderedBoxes.filter((box) => box.translatedText).length,
  }), [pages.length, orderedBoxes]);

  useEffect(() => {
    function onKeyDown(event) {
      if (!(event.ctrlKey || event.metaKey)) return;
      if (isEditableTarget(event.target)) return;
      const key = event.key.toLowerCase();
      if (key === "z" && !event.shiftKey) {
        event.preventDefault();
        undoImageEdit().catch((error) => setNotice(error.message));
      }
      if (key === "y" || (key === "z" && event.shiftKey)) {
        event.preventDefault();
        redoImageEdit().catch((error) => setNotice(error.message));
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [session.projectId, session.episodeId]);

  async function loadProjects() {
    const items = await api.projects();
    setProjects(items);
    return items;
  }

  async function searchProjectMetadata(projectId, query) {
    if (!projectId) return;
    setMetadataBusyProjectId(projectId);
    try {
      const results = await api.searchProjectMetadata(projectId, query);
      setMetadataCandidates({ projectId, items: results.candidates || [], errors: results.errors || [] });
      const count = results.candidates?.length || 0;
      setNotice(count ? `${count} metadata adayı bulundu. Doğru sonucu seçerek kaydet.` : "Uygun metadata adayı bulunamadı.");
    } catch (error) {
      setNotice(error.message);
      throw error;
    } finally {
      setMetadataBusyProjectId("");
    }
  }

  async function fetchProjectMetadata(projectId, candidate) {
    if (!projectId || !candidate) return;
    setMetadataBusyProjectId(projectId);
    try {
      const saved = await api.fetchProjectMetadata(projectId, {
        provider: candidate.provider,
        sourceId: candidate.sourceId,
        query: candidate.title,
      });
      await loadProjects();
      setMetadataCandidates({ projectId: "", items: [], errors: [] });
      setNotice(`${saved.title || projectId} bilgileri kaydedildi.`);
    } catch (error) {
      setNotice(error.message);
      throw error;
    } finally {
      setMetadataBusyProjectId("");
    }
  }

  async function saveProjectMetadata(projectId, metadata) {
    if (!projectId) return;
    setMetadataBusyProjectId(projectId);
    try {
      const saved = await api.saveProjectMetadata(projectId, metadata);
      await loadProjects();
      setNotice(`${saved.title || projectId} bilgileri kaydedildi.`);
    } catch (error) {
      setNotice(error.message);
      throw error;
    } finally {
      setMetadataBusyProjectId("");
    }
  }

  async function clearProjectMetadata(projectId) {
    if (!projectId) return;
    const accepted = window.confirm("Bu projenin metadata bilgileri ve kapak görseli temizlenecek.");
    if (!accepted) return;
    setMetadataBusyProjectId(projectId);
    try {
      await api.clearProjectMetadata(projectId);
      await loadProjects();
      setMetadataCandidates({ projectId: "", items: [], errors: [] });
      setNotice("Proje bilgileri temizlendi.");
    } catch (error) {
      setNotice(error.message);
      throw error;
    } finally {
      setMetadataBusyProjectId("");
    }
  }

  async function uploadProjectCover(projectId, file) {
    if (!projectId || !file) return;
    setMetadataBusyProjectId(projectId);
    try {
      await api.uploadProjectCover(projectId, file);
      await loadProjects();
      setNotice("Kapak görseli kaydedildi.");
    } catch (error) {
      setNotice(error.message);
      throw error;
    } finally {
      setMetadataBusyProjectId("");
    }
  }

  async function openSession(projectId = session.projectId, episodeId = session.episodeId) {
    if (!projectId || !episodeId) return;
    const data = await api.openSession(projectId, episodeId);
    const ordered = orderBoxesByReadingPosition(data.state.boxes || [], data.pages);
    const orderedMasks = orderManualMasks(data.state.manualMasks || [], data.pages);
    setSession({ projectId, episodeId });
    setPages(data.pages);
    setBoxes(ordered);
    setManualMasks(orderedMasks);
    setActivePageId(data.pages[0]?.id || "");
    setActiveBoxId(ordered[0]?.id || "");
    setSelectedBoxIds(ordered[0]?.id ? [ordered[0].id] : []);
    setNotice("");
    setView("editor");
  }

  async function refreshState() {
    if (!session.projectId || !session.episodeId) return;
    const data = await api.openSession(session.projectId, session.episodeId);
    const ordered = orderBoxesByReadingPosition(data.state.boxes || [], data.pages);
    const orderedMasks = orderManualMasks(data.state.manualMasks || [], data.pages);
    setPages(data.pages);
    setBoxes(ordered);
    setManualMasks(orderedMasks);
    setSelectedBoxIds((current) => current.filter((id) => ordered.some((box) => box.id === id)));
    setJobs(await api.jobs());
    return { pages: data.pages, boxes: ordered, manualMasks: orderedMasks };
  }

  async function mergePageWithNext(pageId = activePage?.id) {
    if (!session.projectId || !session.episodeId || !pageId) return;
    const pageIndex = pages.findIndex((page) => page.id === pageId);
    const page = pages[pageIndex];
    const nextPage = pages[pageIndex + 1];
    if (!page || !nextPage) {
      setNotice("Bu sayfadan sonra birleştirilecek sayfa yok.");
      return;
    }
    const accepted = window.confirm(
      `${page.name} ile ${nextPage.name} tek sayfa yapılacak. İkinci sayfa listeden kaldırılır ve görsel yedeği alınır.`,
    );
    if (!accepted) return;

    try {
      const data = await api.mergePageWithNext(session, pageId);
      const ordered = orderBoxesByReadingPosition(data.state.boxes || [], data.pages);
      const orderedMasks = orderManualMasks(data.state.manualMasks || [], data.pages);
      setPages(data.pages);
      setBoxes(ordered);
      setManualMasks(orderedMasks);
      setActivePageId(pageId);
      setActiveBoxId((current) => {
        if (current && ordered.some((box) => box.id === current)) return current;
        return ordered.find((box) => box.pageId === pageId)?.id || ordered[0]?.id || "";
      });
      setSelectedBoxIds((current) => current.filter((id) => ordered.some((box) => box.id === id)));
      setImageVersion(Date.now());
      setScrollTarget({ type: "page", pageId, nonce: Date.now() });
      setNotice(data.merge?.message || "Sayfalar birleştirildi.");
    } catch (error) {
      setNotice(error.message);
      await refreshState();
    }
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
    const box = await api.createBox(session, pageId, bbox, { fontFamily: defaultFont || "noto-sans-black", fontSize: defaultFontSize || 28 });
    await refreshState();
    setActivePageId(pageId);
    setActiveBoxId(box.id);
    setSelectedBoxIds([box.id]);
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

  async function patchBoxForSelection(boxId, patch, options = {}) {
    const ids = actionBoxIds(boxId);
    const patchKeys = Object.keys(patch);
    const canBatch = ids.length > 1 && patch.style && patchKeys.every((key) => key === "style" || key === "corners");
    if (canBatch) {
      const currentBox = boxes.find((item) => item.id === boxId);
      const stylePatch = options.stylePatch || diffTextStyle(patch.style, currentBox?.style || {});
      const hasStylePatch = Object.keys(stylePatch).length > 0;
      const hasCorners = Object.prototype.hasOwnProperty.call(patch, "corners");
      if (!hasStylePatch && !hasCorners) return null;
      setBoxes((items) => orderBoxesByReadingPosition(items.map((item) => {
        if (!ids.includes(item.id)) return item;
        return {
          ...item,
          ...(hasCorners ? { corners: patch.corners } : {}),
          ...(hasStylePatch ? { style: { ...(item.style || {}), ...stylePatch } } : {}),
        };
      }), pages));
      try {
        if (hasStylePatch) await api.applyStyle(session, stylePatch, ids);
        if (hasCorners) {
          await Promise.all(ids.map((id) => api.updateBox(session, id, { corners: patch.corners })));
        }
        await refreshState();
      } catch (error) {
        setNotice(error.message);
        await refreshState();
        throw error;
      }
      return null;
    }
    return patchBox(boxId, patch);
  }

  async function removeBoxes(boxIds) {
    for (const boxId of boxIds) {
      await api.deleteBox(session, boxId);
    }
    setBoxes((items) => orderBoxesByReadingPosition(items.filter((item) => !boxIds.includes(item.id)), pages));
    setSelectedBoxIds((items) => items.filter((id) => !boxIds.includes(id)));
    setActiveBoxId("");
  }

  async function restoreBox(boxId) {
    const updated = await api.restoreBox(session, boxId);
    setBoxes((items) => items.map((item) => (item.id === boxId ? updated : item)));
    setImageVersion(Date.now());
    setActiveBoxId(boxId);
    setNotice("");
  }

  async function restoreBoxes(boxIds) {
    for (const boxId of boxIds) {
      await api.restoreBox(session, boxId);
    }
    setImageVersion(Date.now());
    await refreshState();
    setActiveBoxId(boxIds[0] || "");
    setSelectedBoxIds(boxIds);
    setNotice("");
  }

  async function manualInpaint(pageId, maskPayload) {
    if (!session.projectId || !session.episodeId) return;
    try {
      const result = await api.manualInpaint(session, pageId, maskPayload.mask, maskPayload.bbox);
      setJobs((items) => [result, ...items.filter((item) => item.id !== result.id)]);
      setImageVersion(Date.now());
      await refreshState();
      if (result.status === "failed") {
        throw new Error(result.message || "Fırça temizliği başarısız oldu.");
      }
      setNotice("");
    } catch (error) {
      setNotice(error.message);
      throw error;
    }
  }

  async function restoreBrush(pageId, maskPayload) {
    if (!session.projectId || !session.episodeId) return;
    try {
      const result = await api.restoreBrush(session, pageId, maskPayload.mask, maskPayload.bbox);
      setJobs((items) => [result, ...items.filter((item) => item.id !== result.id)]);
      setImageVersion(Date.now());
      await refreshState();
      if (result.status === "failed") {
        throw new Error(result.message || "Orijinal pikseller geri getirilemedi.");
      }
      setNotice("");
    } catch (error) {
      setNotice(error.message);
      throw error;
    }
  }

  async function undoImageEdit() {
    if (!session.projectId || !session.episodeId) return;
    await api.undo(session);
    setImageVersion(Date.now());
    await refreshState();
    setNotice("");
  }

  async function redoImageEdit() {
    if (!session.projectId || !session.episodeId) return;
    await api.redo(session);
    setImageVersion(Date.now());
    await refreshState();
    setNotice("");
  }

  function actionBoxIds(boxId = activeBoxId) {
    if (boxId && validSelectedBoxIds.includes(boxId)) return validSelectedBoxIds;
    return boxId ? [boxId] : validSelectedBoxIds;
  }

  function selectBox(boxId, pageId, additive = false, scrollType = "inspector", preserveSelection = false) {
    setActivePageId(pageId);
    setActiveBoxId(boxId);
    setWarpEditBoxId((current) => (current && current !== boxId ? "" : current));
    setSelectedBoxIds((current) => {
      if (preserveSelection && current.includes(boxId)) return current;
      if (!additive) return [boxId];
      const base = current.length ? current : activeBoxId ? [activeBoxId] : [];
      if (base.includes(boxId)) {
        const next = base.filter((id) => id !== boxId);
        return next.length ? next : [boxId];
      }
      return [...base, boxId];
    });
    setScrollTarget({ type: scrollType, boxId, pageId, nonce: Date.now() });
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
    setView(session.projectId && session.episodeId ? "editor" : "projects");
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

  if (view === "projects") {
    return (
      <div className="app-shell page-mode">
        <PageTopbar
          project={activeProject}
          episode={activeEpisode}
          stats={sessionStats}
          jobs={jobs}
          onOpenProjects={() => setView("projects")}
          onOpenSettings={() => setView("settings")}
          onOpenEditor={() => setView("editor")}
          canOpenEditor={Boolean(activePage)}
          onSave={() => runJob("save")}
        />
        <ProjectHome
          projects={projects}
          episodes={episodes}
          session={session}
          notice={notice}
          metadataBusyProjectId={metadataBusyProjectId}
          metadataCandidates={metadataCandidates.projectId === session.projectId ? metadataCandidates.items : []}
          metadataErrors={metadataCandidates.projectId === session.projectId ? metadataCandidates.errors : []}
          onProject={(projectId) => {
            setSession({ projectId, episodeId: "" });
            setMetadataCandidates({ projectId: "", items: [], errors: [] });
          }}
          onOpenEpisode={(episodeId) => {
            const next = { ...session, episodeId };
            setSession(next);
            openSession(next.projectId, next.episodeId).catch((error) => setNotice(error.message));
          }}
          onSearchMetadata={searchProjectMetadata}
          onFetchMetadata={fetchProjectMetadata}
          onSaveMetadata={saveProjectMetadata}
          onClearMetadata={clearProjectMetadata}
          onUploadCover={uploadProjectCover}
          onOpenSettings={() => setView("settings")}
        />
      </div>
    );
  }

  if (view === "settings") {
    return (
      <div className="app-shell page-mode">
        <PageTopbar
          project={activeProject}
          episode={activeEpisode}
          stats={sessionStats}
          jobs={jobs}
          onOpenProjects={() => setView("projects")}
          onOpenSettings={() => setView("settings")}
          onOpenEditor={() => setView("editor")}
          canOpenEditor={Boolean(activePage)}
          onSave={() => runJob("save")}
        />
        <SettingsPage
          settings={settings}
          fonts={fonts}
          onClose={() => setView(session.projectId && session.episodeId ? "editor" : "projects")}
          onSave={saveSettings}
          onUploadFont={(file, name) => uploadFont(file, name)}
        />
      </div>
    );
  }

  return (
    <div className="app-shell">
      <PageTopbar
        project={activeProject}
        episode={activeEpisode}
        stats={sessionStats}
        jobs={jobs}
        onOpenProjects={() => setView("projects")}
        onOpenSettings={() => setView("settings")}
        onOpenEditor={() => setView("editor")}
        canOpenEditor={Boolean(activePage)}
        onSave={() => runJob("save")}
      >
        <div className="toolbar">
          <span className="toolbar-label">Araç</span>
          <ToolButton active={tool === "select"} icon={MousePointer2} label="Seç" onClick={() => setTool("select")} />
          <ToolButton active={tool === "box"} icon={BoxSelect} label="Yazı alanı çiz" onClick={() => setTool("box")} />
          <ToolButton active={tool === "brush"} icon={Paintbrush} label="Fırça ile temizle" onClick={() => setTool("brush")} />
          <ToolButton active={tool === "restore"} icon={Eraser} label="Orijinal silgisi" onClick={() => setTool("restore")} />
          {tool === "brush" ? (
            <BrushToolbar
              size={brushSize}
              mode={brushMode}
              onSizeChange={setBrushSize}
              onModeChange={setBrushMode}
            />
          ) : null}
          {tool === "restore" ? (
            <RestoreToolbar size={brushSize} onSizeChange={setBrushSize} />
          ) : null}
          <ToolButton icon={ZoomOut} label="Uzaklaş" onClick={() => setZoom((value) => Math.max(0.3, value - 0.08))} />
          <span className="zoom-label">{Math.round(zoom * 100)}%</span>
          <ToolButton icon={ZoomIn} label="Yakınlaş" onClick={() => setZoom((value) => Math.min(1.4, value + 0.08))} />
        </div>
      </PageTopbar>

      <main className="workspace">
        <PageSidebar
          boxes={orderedBoxes}
          pages={pages}
          activePageId={activePage?.id}
          onBackToProjects={() => setView("projects")}
          onMergeNext={mergePageWithNext}
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
              manualMasks={manualMasks}
              activePageId={activePage.id}
              activeBoxId={activeBoxId}
              selectedBoxIds={validSelectedBoxIds}
              tool={tool}
              zoom={zoom}
              brushSize={brushSize}
              brushMode={brushMode}
              imageVersion={imageVersion}
              scrollTarget={scrollTarget}
              warpEditBoxId={warpEditBoxId}
              onCreateBox={createBox}
              onManualInpaint={manualInpaint}
              onRestoreBrush={restoreBrush}
              onBrushError={(message) => setNotice(message)}
              onSelectPage={setActivePageId}
              onSelectBox={(boxId, pageId, additive, preserveSelection) => selectBox(boxId, pageId, additive, "inspector", preserveSelection)}
              onPatchBox={patchBoxForSelection}
              fonts={fonts}
            />
          ) : (
            <EmptyState />
          )}
        </section>

        <Inspector
          box={activeBox}
          boxes={orderedBoxes}
          selectedBoxIds={validSelectedBoxIds}
          pages={pages}
          fonts={fonts}
          scrollTarget={scrollTarget}
          onSelect={(boxId, additive, preserveSelection) => {
            const selected = boxes.find((item) => item.id === boxId);
            if (selected) selectBox(boxId, selected.pageId, additive, "canvas", preserveSelection);
          }}
          onPatch={patchBoxForSelection}
          onDelete={(box) => removeBoxes(actionBoxIds(box.id)).catch((error) => setNotice(error.message))}
          onSingleOcr={(box) => runJob("ocr", { boxIds: actionBoxIds(box.id) })}
          onSingleInpaint={(box) => runJob("inpaint", { boxIds: actionBoxIds(box.id) })}
          onSinglePlace={(box) => runJob("place", { boxIds: actionBoxIds(box.id) })}
          onSingleUnplace={(box) => runJob("unplace", { boxIds: actionBoxIds(box.id) })}
          onRestoreOriginal={(box) => restoreBoxes(actionBoxIds(box.id)).catch((error) => setNotice(error.message))}
          warpEditBoxId={warpEditBoxId}
          onToggleWarpEdit={toggleWarpEdit}
        />
      </main>
    </div>
  );
}

function PageTopbar({
  project,
  episode,
  stats,
  jobs,
  children,
  onOpenProjects,
  onOpenSettings,
  onOpenEditor,
  canOpenEditor,
  onSave,
}) {
  return (
    <header className={children ? "topbar" : "topbar page-topbar"}>
      <div className="brand">
        <span className="brand-mark">WT</span>
        <div>
          <strong>Webtoon Translation Studio</strong>
          <small>Yerel çeviri ve düzenleme stüdyosu</small>
        </div>
        <nav className="top-nav" aria-label="Ana gezinme">
          <button type="button" onClick={onOpenProjects}><Home size={15} /> Projeler</button>
          <button type="button" onClick={onOpenEditor} disabled={!canOpenEditor}><FileImage size={15} /> Editör</button>
          <button type="button" onClick={onOpenSettings}><Settings size={15} /> Ayarlar</button>
        </nav>
      </div>
      <SessionSummary project={project} episode={episode} stats={stats} />
      {children || <div className="toolbar page-toolbar"><span className="toolbar-label">Stüdyo</span></div>}
      <JobStatusBar jobs={jobs} />
      <div className="top-actions">
        <button className="primary-action" onClick={onSave} disabled={!canOpenEditor}>
          <Save size={17} /> Kaydet
        </button>
      </div>
    </header>
  );
}

function SessionSummary({ project, episode, stats }) {
  const hasEpisode = Boolean(project && episode);
  return (
    <section className={hasEpisode ? "session-summary" : "session-summary muted"} aria-label="Aktif bölüm">
      <div>
        <span>{project?.name || "Proje seçilmedi"}</span>
        <strong>{episode?.name || "Bölüm bekleniyor"}</strong>
      </div>
      <div className="summary-metrics">
        <span>{stats.pages} sayfa</span>
        <span>{stats.boxes} kutu</span>
        <span>{stats.placed} yerleşti</span>
      </div>
    </section>
  );
}

function ProjectHome({
  projects,
  episodes,
  session,
  notice,
  metadataBusyProjectId,
  metadataCandidates,
  metadataErrors,
  onProject,
  onOpenEpisode,
  onSearchMetadata,
  onFetchMetadata,
  onSaveMetadata,
  onClearMetadata,
  onUploadCover,
  onOpenSettings,
}) {
  const activeProject = projects.find((project) => project.id === session.projectId);
  const activeMetadata = activeProject?.metadata || {};
  const [lookupQuery, setLookupQuery] = useState("");
  const [metadataDraft, setMetadataDraft] = useState(projectMetadataDraft(activeProject));
  const metadataBusy = metadataBusyProjectId === activeProject?.id;
  const coverInputRef = useRef(null);

  useEffect(() => {
    setLookupQuery(activeMetadata.title || activeProject?.folderName || activeProject?.name || "");
    setMetadataDraft(projectMetadataDraft(activeProject));
  }, [activeProject?.id, activeMetadata.updatedAt]);

  return (
    <main className="project-page">
      <section className="project-hero">
        <div>
          <span className="panel-kicker">Kütüphane</span>
          <h1>Projeler</h1>
          <p>Kapak, yazar bilgisi ve bölümler aynı ekranda; editöre geçmeden önce çalışacağın seriyi seç.</p>
        </div>
        <button type="button" className="ghost" onClick={onOpenSettings}><Settings size={16} /> Ayarlar</button>
      </section>
      {notice ? <div className="notice project-notice">{notice}</div> : null}
      <section className="project-layout">
        <section className="project-library-panel">
          <div className="panel-head">
            <div>
              <span className="panel-kicker">Seriler</span>
              <h2>Proje Kütüphanesi</h2>
            </div>
            <span className="count-badge">{projects.length}</span>
          </div>
          <div className="project-grid">
            {projects.length ? projects.map((project) => (
              <button
                key={project.id}
                type="button"
                className={project.id === session.projectId ? "project-card active" : "project-card"}
                onClick={() => onProject(project.id)}
              >
                <ProjectCover project={project} />
                <span className="project-card-body">
                  <strong>{project.metadata?.title || project.name}</strong>
                  <small>{project.metadata?.author || project.folderName || project.id}</small>
                  <span className="project-card-meta">
                    <span>{project.episodeCount || 0} bölüm</span>
                    {project.metadata?.status ? <span>{project.metadata.status}</span> : null}
                  </span>
                </span>
              </button>
            )) : (
              <div className="side-empty">
                data/projects altında proje klasörü bulunduğunda burada listelenir.
              </div>
            )}
          </div>
        </section>

        <aside className="project-detail-panel">
          <div className="panel-head">
            <div>
              <span className="panel-kicker">Seçili Proje</span>
              <h2>{activeProject?.metadata?.title || activeProject?.name || "Proje seç"}</h2>
            </div>
            {activeProject ? <span className="count-badge">{episodes.length}</span> : null}
          </div>
          {activeProject ? (
            <>
              <div className="project-detail-head">
                <ProjectCover project={activeProject} large />
                <div>
                  <strong>{activeMetadata.title || activeProject.name}</strong>
                  <small>{[activeMetadata.author, activeMetadata.artist].filter(Boolean).join(" / ") || activeProject.folderName}</small>
                  <div className="project-tags">
                    {activeMetadata.year ? <span>{activeMetadata.year}</span> : null}
                    {activeMetadata.status ? <span>{activeMetadata.status}</span> : null}
                    {(activeMetadata.genres || []).slice(0, 3).map((genre) => <span key={genre}>{genre}</span>)}
                  </div>
                </div>
              </div>

              <form
                className="metadata-box"
                onSubmit={(event) => {
                  event.preventDefault();
                  onSaveMetadata(activeProject.id, projectMetadataPayload(metadataDraft)).catch(() => {});
                }}
              >
                <label>
                  Başlık
                  <input value={metadataDraft.title} onChange={(event) => setMetadataDraft((draft) => ({ ...draft, title: event.target.value }))} />
                </label>
                <label>
                  Orijinal ad
                  <input value={metadataDraft.originalTitle} onChange={(event) => setMetadataDraft((draft) => ({ ...draft, originalTitle: event.target.value }))} />
                </label>
                <div className="metadata-fields">
                  <label>
                    Yazar
                    <input value={metadataDraft.author} onChange={(event) => setMetadataDraft((draft) => ({ ...draft, author: event.target.value }))} />
                  </label>
                  <label>
                    Çizer
                    <input value={metadataDraft.artist} onChange={(event) => setMetadataDraft((draft) => ({ ...draft, artist: event.target.value }))} />
                  </label>
                  <label>
                    Durum
                    <input value={metadataDraft.status} onChange={(event) => setMetadataDraft((draft) => ({ ...draft, status: event.target.value }))} />
                  </label>
                  <label>
                    Yıl
                    <input value={metadataDraft.year} onChange={(event) => setMetadataDraft((draft) => ({ ...draft, year: event.target.value }))} />
                  </label>
                </div>
                <label>
                  Açıklama
                  <textarea value={metadataDraft.description} onChange={(event) => setMetadataDraft((draft) => ({ ...draft, description: event.target.value }))} />
                </label>
                <label>
                  Alternatif adlar
                  <textarea value={metadataDraft.synonyms} onChange={(event) => setMetadataDraft((draft) => ({ ...draft, synonyms: event.target.value }))} />
                </label>
                <div className="metadata-actions">
                  <input value={lookupQuery} onChange={(event) => setLookupQuery(event.target.value)} placeholder="MangaDex + WEBTOON + AniList araması" />
                  <button type="button" className="ghost" disabled={metadataBusy} onClick={() => onSearchMetadata(activeProject.id, lookupQuery).catch(() => {})}>
                    <Search size={15} /> {metadataBusy ? "Aranıyor" : "Ara"}
                  </button>
                </div>
                <input
                  ref={coverInputRef}
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  className="hidden-file-input"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (file) onUploadCover(activeProject.id, file).catch(() => {});
                    event.target.value = "";
                  }}
                />
                <div className="metadata-button-row">
                  <button type="button" className="ghost" disabled={metadataBusy} onClick={() => coverInputRef.current?.click()}>
                    <Plus size={15} /> Kapak yükle
                  </button>
                  <button type="button" className="ghost danger" disabled={metadataBusy} onClick={() => onClearMetadata(activeProject.id).catch(() => {})}>
                    <Trash2 size={15} /> Temizle
                  </button>
                  <button type="submit" className="ghost" disabled={metadataBusy}>
                    <Save size={15} /> Kaydet
                  </button>
                </div>
              </form>

              {metadataCandidates.length || metadataErrors.length ? (
                <div className="metadata-candidates">
                  {metadataCandidates.length ? (
                    <>
                      <div className="panel-section-head">
                        <span>Metadata adayları</span>
                        <small>{metadataCandidates.length}</small>
                      </div>
                      {metadataCandidates.map((candidate) => (
                        <MetadataCandidate
                          key={`${candidate.provider}-${candidate.sourceId}`}
                          candidate={candidate}
                          busy={metadataBusy}
                          onSelect={() => onFetchMetadata(activeProject.id, candidate).catch(() => {})}
                        />
                      ))}
                    </>
                  ) : null}
                  {metadataErrors.map((error) => (
                    <div className="side-empty" key={error.provider}>{error.provider}: {error.message}</div>
                  ))}
                </div>
              ) : null}

              <div className="panel-section-head">
                <span>Bölümler</span>
                <small>{episodes.length || "Boş"}</small>
              </div>
              <div className="episode-grid compact">
                {episodes.length ? episodes.map((episode) => (
                  <button
                    key={episode.id}
                    type="button"
                    className="episode-card"
                    onClick={() => onOpenEpisode(episode.id)}
                  >
                    <span className="episode-icon"><FileImage size={18} /></span>
                    <span>
                      <strong>{episode.name}</strong>
                      <small>Editörde aç</small>
                    </span>
                    <ChevronRight size={16} />
                  </button>
                )) : (
                  <div className="empty-panel">
                    <CircleAlert size={22} />
                    <h2>Bölüm bulunamadı</h2>
                    <p>Bu proje altında bölüm klasörü varsa backend yeniden tarandığında burada görünür.</p>
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="empty-panel">
              <FolderOpen size={24} />
              <h2>Proje seç</h2>
              <p>Kütüphaneden bir seri seçildiğinde metadata ve bölümler burada görünür.</p>
            </div>
          )}
        </aside>
      </section>
    </main>
  );
}

function ProjectCover({ project, large = false }) {
  const version = project?.metadata?.updatedAt || project?.metadata?.coverFile || "";
  const hasCover = Boolean(project?.hasCover);
  return (
    <span className={large ? "project-cover large" : "project-cover"}>
      <span className="project-cover-fallback"><FileImage size={large ? 28 : 20} /></span>
      {hasCover ? (
        <img
          src={api.projectCoverUrl(project.id, version)}
          alt={project.metadata?.title || project.name}
          loading="lazy"
          onError={(event) => {
            event.currentTarget.remove();
          }}
        />
      ) : null}
    </span>
  );
}

function MetadataCandidate({ candidate, busy, onSelect }) {
  const aliases = (candidate.synonyms || []).filter((item) => item && item !== candidate.title).slice(0, 3);
  return (
    <div className="metadata-candidate">
      <span className="candidate-cover">
        {candidate.coverUrl ? <img src={api.metadataCoverPreviewUrl(candidate.coverUrl)} alt={candidate.title} loading="lazy" /> : <FileImage size={18} />}
      </span>
      <div>
        <div className="candidate-title">
          <strong>{candidate.title || candidate.originalTitle || "Adsız kayıt"}</strong>
          <span>{candidate.provider}</span>
        </div>
        {candidate.originalTitle ? <small>{candidate.originalTitle}</small> : null}
        {aliases.length ? <p>{aliases.join(" / ")}</p> : null}
        <div className="project-card-meta">
          <span>Skor {candidate.score || 0}</span>
          {candidate.year ? <span>{candidate.year}</span> : null}
          {candidate.author ? <span>{candidate.author}</span> : null}
        </div>
      </div>
      <button type="button" className="ghost" disabled={busy} onClick={onSelect}>Seç</button>
    </div>
  );
}

function projectMetadataDraft(project) {
  const metadata = project?.metadata || {};
  return {
    title: metadata.title || project?.name || "",
    originalTitle: metadata.originalTitle || "",
    author: metadata.author || "",
    artist: metadata.artist || "",
    status: metadata.status || "",
    year: metadata.year || "",
    description: metadata.description || "",
    synonyms: (metadata.synonyms || []).join("\n"),
  };
}

function projectMetadataPayload(draft) {
  return {
    ...draft,
    synonyms: String(draft.synonyms || "")
      .split("\n")
      .map((item) => item.trim())
      .filter(Boolean),
  };
}

function PageSidebar({ boxes, pages, activePageId, onBackToProjects, onPage, onMergeNext }) {
  const placedCount = boxes.filter((box) => box.status === "placed").length;
  const translatedCount = boxes.filter((box) => box.translatedText).length;
  const activeIndex = pages.findIndex((page) => page.id === activePageId);
  const activePage = pages[activeIndex];
  const nextPage = pages[activeIndex + 1];
  const canMergeNext = Boolean(activePage && nextPage);
  return (
    <aside className="sidebar">
      <div className="panel-head">
        <div>
          <span className="panel-kicker">Bölüm</span>
          <h2>Sayfalar</h2>
        </div>
        <button type="button" className="tool" onClick={onBackToProjects} title="Projelere dön" aria-label="Projelere dön"><Home size={17} /></button>
      </div>

      <div className="sidebar-metrics" aria-label="Bölüm özeti">
        <Metric label="Sayfa" value={pages.length} />
        <Metric label="Kutu" value={boxes.length} />
        <Metric label="Çeviri" value={translatedCount} />
        <Metric label="Yerleşti" value={placedCount} />
      </div>

      <div className="page-merge-panel">
        <button type="button" className="merge-page-button" onClick={() => onMergeNext(activePageId)} disabled={!canMergeNext}>
          <Layers3 size={16} /> Sonrakiyle birleştir
        </button>
        <small>{canMergeNext ? `${activePage.name} + ${nextPage.name}` : "Aktif sayfadan sonra sayfa yok"}</small>
      </div>

      <div className="panel-section-head">
        <span>Sayfalar</span>
        <small>{pages.length || "Boş"}</small>
      </div>
      {pages.length ? (
        <div className="page-list">
          {pages.map((page, index) => (
            <button key={page.id} className={page.id === activePageId ? "page-row active" : "page-row"} onClick={() => onPage(page.id)}>
              <FileImage size={16} />
              <span>{index + 1}. {page.name}</span>
              <ChevronRight size={15} />
            </button>
          ))}
        </div>
      ) : (
        <div className="side-empty">
          Proje ve bölüm seçildiğinde sayfalar burada listelenir.
        </div>
      )}
    </aside>
  );
}

function Metric({ label, value }) {
  return (
    <div>
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function StatusBadge({ status }) {
  const normalized = normalizeStatus(status);
  const Icon = normalized === "placed" ? CheckCircle2 : normalized === "failed" ? CircleAlert : Clock3;
  return (
    <span className={`status-badge status-${normalized}`}>
      <Icon size={12} />
      {statusLabel(status)}
    </span>
  );
}

function ActionBar({ targetLanguage, setTargetLanguage, fonts, defaultFont, onDefaultFontChange, runJob, refreshState }) {
  return (
    <div className="actionbar" aria-label="Bölüm işlemleri">
      <div className="action-group">
        <span>Hazırlık</span>
        <button onClick={() => runJob("detect")}><WandSparkles size={16} /> Yazıları seç</button>
        <button onClick={() => runJob("ocr")}><ScanText size={16} /> OCR</button>
        <button onClick={() => runJob("inpaint")}><Eraser size={16} /> Sil</button>
      </div>
      <div className="action-group">
        <span>Çeviri</span>
        <div className="language-control">
          <Languages size={16} />
          <input value={targetLanguage} onChange={(event) => setTargetLanguage(event.target.value.toUpperCase())} aria-label="Hedef dil" />
        </div>
        <select className="font-control" value={defaultFont || fonts[0]?.id || ""} onChange={(event) => onDefaultFontChange(event.target.value)} aria-label="Varsayılan font">
          {fonts.map((font) => (
            <option key={font.id} value={font.id}>{font.name}</option>
          ))}
        </select>
        <button onClick={() => runJob("translate", { targetLanguage })}><Languages size={16} /> Çevir</button>
      </div>
      <div className="action-group">
        <span>Çıktı</span>
        <button onClick={() => runJob("place")}><AlignCenter size={16} /> Yerleştir</button>
        <button onClick={() => runJob("unplace")}><X size={16} /> Kaldır</button>
        <button className="ghost" onClick={refreshState}><RefreshCcw size={16} /> Yenile</button>
      </div>
    </div>
  );
}

function JobStatusBar({ jobs }) {
  const job = visibleJob(jobs);
  if (!job) {
    return (
      <div className="job-status idle">
        <div>
          <span>Hazır</span>
          <strong>İş kuyruğu beklemede</strong>
          <em>0%</em>
        </div>
        <b><i style={{ width: "0%" }} /></b>
      </div>
    );
  }
  const progress = clamp(Number(job.progress || 0), 0, 100);
  const detectorText = job.type === "detect" ? detectorJobText(job.detector) : "";
  return (
    <div className={`job-status ${job.status}`}>
      <div>
        <span>{jobLabel(job.type)}</span>
        <strong>{job.message || job.status}</strong>
        <em>{Math.round(progress)}%</em>
      </div>
      {detectorText ? <small>{detectorText}</small> : null}
      <b><i style={{ width: `${progress}%` }} /></b>
    </div>
  );
}

function BrushToolbar({ size, mode, onSizeChange, onModeChange }) {
  return (
    <div className="brush-toolbar">
      <ToolButton active={mode === "paint"} icon={Paintbrush} label="Maske boya" onClick={() => onModeChange("paint")} />
      <ToolButton active={mode === "erase"} icon={Eraser} label="Maske silgisi" onClick={() => onModeChange("erase")} />
      <label>
        <span>{size}px</span>
        <input type="range" min="6" max="110" step="2" value={size} onChange={(event) => onSizeChange(Number(event.target.value))} />
      </label>
    </div>
  );
}

function RestoreToolbar({ size, onSizeChange }) {
  return (
    <div className="brush-toolbar restore-toolbar">
      <span>Orijinal silgisi</span>
      <label>
        <span>{size}px</span>
        <input type="range" min="6" max="110" step="2" value={size} onChange={(event) => onSizeChange(Number(event.target.value))} />
      </label>
    </div>
  );
}

function WebtoonReader({
  session,
  pages,
  boxes,
  manualMasks,
  activePageId,
  activeBoxId,
  selectedBoxIds,
  tool,
  zoom,
  brushSize,
  brushMode,
  imageVersion,
  scrollTarget,
  warpEditBoxId,
  onCreateBox,
  onManualInpaint,
  onRestoreBrush,
  onBrushError,
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
            manualMasks={manualMasks.filter((mask) => mask.pageId === page.id && mask.status === "cleaned")}
            active={activePageId === page.id}
            activeBoxId={activeBoxId}
            selectedBoxIds={selectedBoxIds}
            tool={tool}
            zoom={zoom}
            brushSize={brushSize}
            brushMode={brushMode}
            imageVersion={imageVersion}
            warpEditBoxId={warpEditBoxId}
            registerBox={(boxId, node) => {
              if (node) boxRefs.current[boxId] = node;
              else delete boxRefs.current[boxId];
            }}
            onCreateBox={onCreateBox}
            onManualInpaint={onManualInpaint}
            onRestoreBrush={onRestoreBrush}
            onBrushError={onBrushError}
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
  manualMasks,
  active,
  activeBoxId,
  selectedBoxIds,
  tool,
  zoom,
  brushSize,
  brushMode,
  imageVersion,
  warpEditBoxId,
  registerBox,
  onCreateBox,
  onManualInpaint,
  onRestoreBrush,
  onBrushError,
  onSelectPage,
  onSelectBox,
  onPatchBox,
  fonts,
}) {
  const stageRef = useRef(null);
  const brushCanvasRef = useRef(null);
  const brushPointRef = useRef(null);
  const [draft, setDraft] = useState(null);
  const [drag, setDrag] = useState(null);
  const [resize, setResize] = useState(null);
  const [warpDrag, setWarpDrag] = useState(null);
  const [hasBrushMask, setHasBrushMask] = useState(false);
  const [brushBusy, setBrushBusy] = useState(false);
  const imageSrc = `${api.imageUrl(session.projectId, session.episodeId, page.id)}&v=${imageVersion}`;

  function point(event) {
    const rect = stageRef.current.getBoundingClientRect();
    return {
      x: (event.clientX - rect.left) / zoom,
      y: (event.clientY - rect.top) / zoom,
    };
  }

  function brushPoint(event) {
    const rect = brushCanvasRef.current.getBoundingClientRect();
    return {
      x: clamp((event.clientX - rect.left) / zoom, 0, page.width),
      y: clamp((event.clientY - rect.top) / zoom, 0, page.height),
    };
  }

  function drawBrushLine(from, to) {
    const canvas = brushCanvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    const size = Math.max(2, Number(brushSize || 36));
    context.save();
    context.lineWidth = size;
    context.lineCap = "round";
    context.lineJoin = "round";
    context.globalCompositeOperation = tool === "brush" && brushMode === "erase" ? "destination-out" : "source-over";
    context.strokeStyle = tool === "restore" ? "rgba(69, 212, 131, 0.72)" : "rgba(231, 189, 84, 0.7)";
    context.fillStyle = tool === "restore" ? "rgba(69, 212, 131, 0.72)" : "rgba(231, 189, 84, 0.7)";
    context.beginPath();
    context.moveTo(from.x, from.y);
    context.lineTo(to.x, to.y);
    context.stroke();
    context.beginPath();
    context.arc(to.x, to.y, size / 2, 0, Math.PI * 2);
    context.fill();
    context.restore();
    if (tool === "restore" || brushMode !== "erase") setHasBrushMask(true);
  }

  function clearBrushMask() {
    const canvas = brushCanvasRef.current;
    if (!canvas) return;
    canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
    setHasBrushMask(false);
  }

  function onBrushPointerDown(event) {
    if (!["brush", "restore"].includes(tool) || brushBusy) return;
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    onSelectPage(page.id);
    const current = brushPoint(event);
    brushPointRef.current = current;
    drawBrushLine(current, current);
  }

  function onBrushPointerMove(event) {
    if (!["brush", "restore"].includes(tool) || !brushPointRef.current || brushBusy) return;
    event.preventDefault();
    event.stopPropagation();
    const current = brushPoint(event);
    drawBrushLine(brushPointRef.current, current);
    brushPointRef.current = current;
  }

  function onBrushPointerUp(event) {
    if (brushPointRef.current) {
      event.preventDefault();
      event.stopPropagation();
    }
    brushPointRef.current = null;
  }

  async function submitBrushMask() {
    if (!hasBrushMask || brushBusy) return;
    setBrushBusy(true);
    try {
      const payload = extractBrushMask(brushCanvasRef.current);
      if (tool === "restore") {
        await onRestoreBrush(page.id, payload);
      } else {
        await onManualInpaint(page.id, payload);
      }
      clearBrushMask();
    } catch (error) {
      onBrushError(error.message);
    } finally {
      setBrushBusy(false);
    }
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
      drag.items.forEach((item) => {
        onPatchBox(item.box.id, {
          bbox: { ...item.box.bbox, x: Math.max(0, item.origin.x + dx), y: Math.max(0, item.origin.y + dy) },
        });
      });
    }
    if (resize) {
      const current = point(event);
      const dx = current.x - resize.start.x;
      const dy = current.y - resize.start.y;
      onPatchBox(resize.box.id, {
        bbox: resizedBox(resize.origin, resize.handle, dx, dy, page.width, page.height),
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
    setResize(null);
    setWarpDrag(null);
  }

  return (
    <section className={active ? "reader-page active" : "reader-page"} ref={refCallback}>
      <div className="reader-page-title">
        <span>{pageIndex + 1}</span>
        <strong>{page.name}</strong>
        <div className="page-tools">
          <em>{boxes.length} yazı</em>
        </div>
      </div>
      <div
        ref={stageRef}
        className={`canvas-page tool-${tool} brush-${brushMode}`}
        style={{ width: page.width * zoom, height: page.height * zoom }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        <img src={imageSrc} alt={page.name} style={{ width: page.width * zoom, height: page.height * zoom }} draggable="false" />
        <div className="overlay" style={{ transform: `scale(${zoom})`, width: page.width, height: page.height }}>
          {tool === "restore" ? manualMasks.map((mask) => (
            <img
              key={mask.id}
              className="restore-mask-overlay"
              src={`${api.manualMaskOverlayUrl(session.projectId, session.episodeId, mask.id)}&v=${imageVersion}`}
              alt=""
              draggable="false"
            />
          )) : null}
          {boxes.map((box) => (
            <div
              key={box.id}
              ref={(node) => registerBox(box.id, node)}
              className={boxClassName(box, activeBoxId, selectedBoxIds)}
              style={{ left: box.bbox.x, top: box.bbox.y, width: box.bbox.w, height: box.bbox.h }}
              onPointerDown={(event) => {
                if (tool !== "select") return;
                event.stopPropagation();
                onSelectPage(page.id);
                const additive = event.ctrlKey || event.metaKey;
                const preserveSelection = !additive && selectedBoxIds.length > 1 && selectedBoxIds.includes(box.id);
                onSelectBox(box.id, page.id, additive, preserveSelection);
                if (additive) return;
                if (warpEditBoxId === box.id) return;
                const draggedBoxes = preserveSelection ? boxes.filter((item) => selectedBoxIds.includes(item.id)) : [box];
                setDrag({
                  items: draggedBoxes.map((item) => ({ box: item, origin: { x: item.bbox.x, y: item.bbox.y } })),
                  start: point(event),
                });
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
              {tool === "select" && box.id === activeBoxId && warpEditBoxId !== box.id ? (
                <ResizeHandles
                  onResizeStart={(event, handle) => {
                    event.preventDefault();
                    event.stopPropagation();
                    onSelectPage(page.id);
                    const preserveSelection = selectedBoxIds.length > 1 && selectedBoxIds.includes(box.id);
                    onSelectBox(box.id, page.id, false, preserveSelection);
                    setDrag(null);
                    setResize({
                      box,
                      handle,
                      origin: { ...box.bbox },
                      start: point(event),
                    });
                  }}
                />
              ) : null}
              <span>{box.order}</span>
              <i>{box.status}</i>
            </div>
          ))}
          {draft ? <div className="box draft" style={{ left: draft.x, top: draft.y, width: draft.w, height: draft.h }} /> : null}
          <canvas
            ref={brushCanvasRef}
            className="brush-mask-canvas"
            width={page.width}
            height={page.height}
            style={{ width: page.width, height: page.height }}
            onPointerDown={onBrushPointerDown}
            onPointerMove={onBrushPointerMove}
            onPointerUp={onBrushPointerUp}
            onPointerCancel={onBrushPointerUp}
          />
        </div>
      </div>
      {active && ["brush", "restore"].includes(tool) ? (
        <div className="brush-floating-actions">
          <button type="button" className="page-tool" onClick={clearBrushMask} disabled={!hasBrushMask || brushBusy} title="Maskeyi temizle">
            <X size={14} />
          </button>
          <button type="button" className="page-tool text" onClick={submitBrushMask} disabled={!hasBrushMask || brushBusy} title={tool === "restore" ? "Orijinal pikselleri geri getir" : "Fırça alanını temizle"}>
            <Eraser size={14} /> {brushBusy ? "İşleniyor" : tool === "restore" ? "Geri getir" : "Temizle"}
          </button>
        </div>
      ) : null}
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

function ResizeHandles({ onResizeStart }) {
  const handles = [
    ["nw", "Sol üstten boyutlandır"],
    ["n", "Üstten boyutlandır"],
    ["ne", "Sağ üstten boyutlandır"],
    ["e", "Sağdan boyutlandır"],
    ["se", "Sağ alttan boyutlandır"],
    ["s", "Alttan boyutlandır"],
    ["sw", "Sol alttan boyutlandır"],
    ["w", "Soldan boyutlandır"],
  ];
  return (
    <div className="resize-handles">
      {handles.map(([handle, title]) => (
        <button
          key={handle}
          type="button"
          className={`resize-handle ${handle}`}
          onPointerDown={(event) => onResizeStart(event, handle)}
          title={title}
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
  selectedBoxIds,
  pages,
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
  const fontSize = positiveNumber(style.fontSize, 28);
  const selectedCount = selectedBoxIds.length;
  const activeSelectionIds = box && selectedBoxIds.includes(box.id) ? selectedBoxIds : box ? [box.id] : [];
  const perspectiveResetStyle = { scaleX: 1, rotation: 0, perspectiveX: 0, perspectiveY: 0, skewX: 0 };

  useEffect(() => {
    if (scrollTarget?.type === "inspector") {
      rowRefs.current[scrollTarget.boxId]?.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [scrollTarget]);

  return (
    <aside className="inspector">
      <div className="panel-head compact">
        <div>
          <span className="panel-kicker">Kutular</span>
          <h2>Yazı Akışı</h2>
        </div>
        <span className="count-badge">{boxes.length}</span>
      </div>
      <div className="box-list">
        {boxes.length ? boxes.map((item) => (
          <button
            key={item.id}
            ref={(node) => {
              if (node) rowRefs.current[item.id] = node;
              else delete rowRefs.current[item.id];
            }}
            className={boxRowClassName(item, box, selectedBoxIds)}
            onClick={(event) => {
              const additive = event.ctrlKey || event.metaKey;
              const preserveSelection = !additive && selectedBoxIds.length > 1 && selectedBoxIds.includes(item.id);
              onSelect(item.id, additive, preserveSelection);
            }}
          >
            <span className="box-order">{boxLabel(item, pages)}</span>
            <span className="box-row-main">
              <strong>{item.translatedText || item.sourceText || "Metin bekliyor"}</strong>
              <small>{item.sourceText ? "Kaynak metin var" : "OCR bekliyor"}</small>
            </span>
            <StatusBadge status={item.status} />
          </button>
        )) : (
          <div className="side-empty">
            Yazıları seçtiğinde veya elle kutu çizdiğinde akış burada görünür.
          </div>
        )}
      </div>

      {box ? (
        <div className="detail">
          <div className="detail-head">
            <div>
              <h2>{selectedCount > 1 && selectedBoxIds.includes(box.id) ? `${selectedCount} Kutu Seçili` : `${boxLabel(box, pages)} Düzenle`}</h2>
              {selectedCount > 1 && selectedBoxIds.includes(box.id) ? <span>Aktif kutu: {boxLabel(box, pages)}</span> : null}
            </div>
            <StatusBadge status={box.status} />
            <button className="icon-danger" onClick={() => onDelete(box)} title={activeSelectionIds.length > 1 ? "Seçili kutuları sil" : "Kutuyu sil"}><Trash2 size={16} /></button>
          </div>
          <section className="detail-section">
            <div className="section-title"><Type size={14} /> Metin</div>
            <label>Orijinal metin</label>
            <textarea value={box.sourceText} onChange={(event) => onPatch(box.id, { sourceText: event.target.value })} />
            <label>Çeviri</label>
            <textarea value={box.translatedText} onChange={(event) => onPatch(box.id, { translatedText: event.target.value })} />
          </section>
          <section className="detail-section">
            <div className="section-title"><Layers3 size={14} /> Hızlı işlemler</div>
            <div className="inline-tools">
              <button onClick={() => onSingleOcr(box)}><Search size={15} /> OCR{activeSelectionIds.length > 1 ? ` (${activeSelectionIds.length})` : ""}</button>
              <button onClick={() => onSingleInpaint(box)}><Eraser size={15} /> Sil{activeSelectionIds.length > 1 ? ` (${activeSelectionIds.length})` : ""}</button>
              <button onClick={() => onSinglePlace(box)}><AlignCenter size={15} /> Yerleştir{activeSelectionIds.length > 1 ? ` (${activeSelectionIds.length})` : ""}</button>
              <button onClick={() => onSingleUnplace(box)}><X size={15} /> Kaldır{activeSelectionIds.length > 1 ? ` (${activeSelectionIds.length})` : ""}</button>
              <button onClick={() => onRestoreOriginal(box)}><RefreshCcw size={15} /> Orijinale dön{activeSelectionIds.length > 1 ? ` (${activeSelectionIds.length})` : ""}</button>
            </div>
          </section>
          <section className="detail-section">
            <div className="section-title"><SlidersHorizontal size={14} /> Stil ve geometri</div>
            <div className="style-grid">
              <label className="wide">Font<select value={style.fontFamily || "noto-sans-black"} onChange={(event) => onPatch(box.id, { style: { ...style, fontFamily: event.target.value } }, { stylePatch: { fontFamily: event.target.value } })}>
                {fonts.map((font) => (
                  <option key={font.id} value={font.id}>{font.name}</option>
                ))}
              </select></label>
              <label>Boyut<input type="number" min="6" max="240" value={fontSize} onChange={(event) => {
                const next = positiveNumber(event.target.value, fontSize);
                onPatch(box.id, { style: { ...style, fontSize: next } }, { stylePatch: { fontSize: next } });
              }} /></label>
              <label>Renk<input type="color" value={style.color || "#111111"} onChange={(event) => onPatch(box.id, { style: { ...style, color: event.target.value } }, { stylePatch: { color: event.target.value } })} /></label>
              <label>Kontur<input type="color" value={style.strokeColor || "#ffffff"} onChange={(event) => onPatch(box.id, { style: { ...style, strokeColor: event.target.value } }, { stylePatch: { strokeColor: event.target.value } })} /></label>
              <button className="toggle" onClick={() => onPatch(box.id, { style: { ...style, bold: !style.bold } }, { stylePatch: { bold: !style.bold } })}><Bold size={15} /> Kalın</button>
              <label>Genişlik <span>{Number(style.scaleX || 1).toFixed(2)}x</span><input type="range" min="0.5" max="2.5" step="0.05" value={style.scaleX || 1} onChange={(event) => {
                const next = Number(event.target.value);
                onPatch(box.id, { style: { ...style, scaleX: next } }, { stylePatch: { scaleX: next } });
              }} /></label>
              <label>Döndür <span>{style.rotation || 0}°</span><input type="range" min="-45" max="45" step="1" value={style.rotation || 0} onChange={(event) => {
                const next = Number(event.target.value);
                onPatch(box.id, { style: { ...style, rotation: next } }, { stylePatch: { rotation: next } });
              }} /></label>
              <label>Perspektif X <span>{style.perspectiveX || 0}</span><input type="range" min="-70" max="70" step="1" value={style.perspectiveX || 0} onChange={(event) => {
                const next = Number(event.target.value);
                onPatch(box.id, { style: { ...style, perspectiveX: next } }, { stylePatch: { perspectiveX: next } });
              }} /></label>
              <label>Perspektif Y <span>{style.perspectiveY || 0}</span><input type="range" min="-70" max="70" step="1" value={style.perspectiveY || 0} onChange={(event) => {
                const next = Number(event.target.value);
                onPatch(box.id, { style: { ...style, perspectiveY: next } }, { stylePatch: { perspectiveY: next } });
              }} /></label>
              <label>Eğiklik <span>{style.skewX || 0}°</span><input type="range" min="-45" max="45" step="1" value={style.skewX || 0} onChange={(event) => {
                const next = Number(event.target.value);
                onPatch(box.id, { style: { ...style, skewX: next } }, { stylePatch: { skewX: next } });
              }} /></label>
              <button className={warpEditBoxId === box.id ? "toggle wide-button active" : "toggle wide-button"} onClick={() => onToggleWarpEdit(box)}><SlidersHorizontal size={15} /> Köşe modu</button>
              <button className="toggle wide-button" onClick={() => onPatch(box.id, { corners: defaultWarpCorners(), style: { ...style, ...perspectiveResetStyle } }, { stylePatch: perspectiveResetStyle })}><SlidersHorizontal size={15} /> Perspektifi sıfırla</button>
            </div>
          </section>
        </div>
      ) : (
        <div className="detail empty-detail">
          <CircleAlert size={24} />
          <h2>Aktif kutu yok</h2>
          <p>Bir kutu seç veya yazı alanı çizerek metin düzenlemeye başla.</p>
        </div>
      )}

    </aside>
  );
}

function SettingsPage({ settings, fonts, onClose, onSave, onUploadFont }) {
  const [draft, setDraft] = useState(() => draftSettings(settings));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [fontFile, setFontFile] = useState(null);
  const [fontName, setFontName] = useState("");
  const [uploadingFont, setUploadingFont] = useState(false);
  const ai = draft.ai;
  const editor = draft.editor;
  const reader = draft.reader;
  const detectionConfig = detectionModelConfig(ai.rtdetrModelId);
  const minAreaPercent = roundDetectorPercent(ai.detectorMinAreaRatio);

  useEffect(() => {
    setDraft(draftSettings(settings));
  }, [settings]);

  function patchAi(patch) {
    setDraft((value) => ({ ...value, ai: { ...value.ai, ...patch } }));
  }

  function changeDetectionModel(modelId) {
    const config = detectionModelConfig(modelId);
    patchAi({
      rtdetrModelId: modelId,
      rtdetrThreshold: config.defaultThreshold,
      rtdetrTextLabels: config.defaultLabels,
      detectorMergeGap: config.showMergeGap ? ai.detectorMergeGap : 18,
    });
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

  function patchReader(patch) {
    setDraft((value) => ({ ...value, reader: { ...value.reader, ...patch } }));
  }

  async function submit(event) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await onSave({
        editor,
        reader,
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
    <main className="settings-page">
      <form className="settings-dialog" onSubmit={submit}>
        <div className="settings-head">
          <div>
            <h2>Ayarlar</h2>
            <span>Yapay zeka, font, temizleme ve reader senkronizasyonu</span>
          </div>
          <div className="settings-head-actions">
            <button type="button" className="ghost" onClick={onClose}><ChevronRight size={16} /> Geri dön</button>
            <button type="submit" className="primary-action" disabled={saving}>{saving ? "Kaydediliyor" : "Kaydet"}</button>
          </div>
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
            <h3>Reader Senkronizasyon</h3>
            <p style={{ fontSize: 12, color: "rgba(255,255,255,0.45)", margin: "0 0 10px" }}>Kaydet sonrası düzenlenmiş görselleri ev sunucusuna rsync ile gönderir.</p>
            <div className="settings-grid">
              <label className="check-row"><input type="checkbox" checked={reader.syncEnabled} onChange={(event) => patchReader({ syncEnabled: event.target.checked })} /> Otomatik senkronizasyon</label>
              <label>Sunucu adresi<input value={reader.syncHost} onChange={(event) => patchReader({ syncHost: event.target.value })} placeholder="user@example.com" /></label>
              <label>Hedef yol<input value={reader.syncPath} onChange={(event) => patchReader({ syncPath: event.target.value })} placeholder="~/webtoon-reader/data/library" /></label>
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
                  ? "GEMINI_API_KEY ortam değişkeni aktif. Buradaki keyler sadece yerel yedek kullanım içindir."
                  : "Çeviri için Gemini API key ekleyin. Keyler yalnızca yerel data/settings.json içinde saklanır."}
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
              <label className="wide">Gemini model<ModelNameInput value={ai.geminiModel} options={GEMINI_MODEL_OPTIONS} onChange={(value) => patchAi({ geminiModel: value })} /></label>
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
              <label className="wide">Algılama modeli<SelectWithOptions value={ai.rtdetrModelId} options={DETECTION_MODEL_OPTIONS} onChange={changeDetectionModel} /></label>
              <p className="settings-note wide">{detectionConfig.note}</p>
              <label>Model çıktısı<input value={detectionConfig.output} readOnly /></label>
              {detectionConfig.showLabelMode ? (
                <label>Algılama modu<SelectWithOptions value={ai.rtdetrTextLabels} options={detectionConfig.labelOptions} onChange={(value) => patchAi({ rtdetrTextLabels: value })} /></label>
              ) : (
                <label>Algılama modu<input value="Modelin sabit çıktısı kullanılır" readOnly /></label>
              )}
              <label>{detectionConfig.thresholdLabel}<input type="number" min="0.05" max="0.95" step="0.01" value={ai.rtdetrThreshold} onChange={(event) => patchAi({ rtdetrThreshold: Number(event.target.value) })} /></label>
              <label>Min alan (%)<input type="number" min="0" max="1" step="0.001" value={minAreaPercent} onChange={(event) => patchAi({ detectorMinAreaRatio: Number(event.target.value) / 100 })} /></label>
              {detectionConfig.showMergeGap ? <label>Birleştirme mesafesi<input type="number" min="0" max="120" step="1" value={ai.detectorMergeGap} onChange={(event) => patchAi({ detectorMergeGap: Number(event.target.value) })} /></label> : null}
              <label className="check-row"><input type="checkbox" checked={ai.detectorFallbackEnabled} onChange={(event) => patchAi({ detectorFallbackEnabled: event.target.checked })} /> Boş sonuçta yerel algılayıcı</label>
              <label>OCR dili<SelectWithOptions value={ai.ocrLanguage} options={OCR_LANGUAGE_OPTIONS} onChange={(value) => patchAi({ ocrLanguage: value })} /></label>
              <label className="check-row"><input type="checkbox" checked={ai.ocrPerspectiveEnabled} onChange={(event) => patchAi({ ocrPerspectiveEnabled: event.target.checked })} /> OCR perspektif kutusu</label>
              <label>Minimum açı<input type="number" min="0" max="45" step="1" value={ai.ocrPerspectiveMinAngle} onChange={(event) => patchAi({ ocrPerspectiveMinAngle: Number(event.target.value) })} /></label>
              <label>Perspektif payı<input type="number" min="0" max="3" step="0.1" value={ai.ocrPerspectivePadding} onChange={(event) => patchAi({ ocrPerspectivePadding: Number(event.target.value) })} /></label>
              <label className="check-row"><input type="checkbox" checked={ai.strictMode} onChange={(event) => patchAi({ strictMode: event.target.checked })} /> Hataları durdur</label>
            </div>
          </section>

          <section className="settings-section">
            <h3>Temizleme</h3>
            <div className="settings-grid">
              <label>IOPaint model<SelectWithOptions value={ai.inpaintModel} options={INPAINT_MODEL_OPTIONS} onChange={(value) => patchAi({ inpaintModel: value })} /></label>
              <label>Cihaz<SelectWithOptions value={ai.aiDevice} options={DEVICE_OPTIONS} onChange={(value) => patchAi({ aiDevice: value })} /></label>
              <label>Maske payı<input type="number" min="0" max="80" value={ai.inpaintPadding} onChange={(event) => patchAi({ inpaintPadding: Number(event.target.value) })} /></label>
              <label className="check-row wide"><input type="checkbox" checked={ai.inpaintPerspectiveMask} onChange={(event) => patchAi({ inpaintPerspectiveMask: event.target.checked })} /> Perspektif maskesiyle sil</label>
            </div>
          </section>
        </div>

        <div className="settings-footer">
          {error ? <span className="settings-error">{error}</span> : null}
          <button type="button" className="ghost" onClick={onClose}>Vazgeç</button>
          <button type="submit" className="primary-action" disabled={saving}>{saving ? "Kaydediliyor" : "Kaydet"}</button>
        </div>
      </form>
    </main>
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

function detectionModelConfig(modelId) {
  return DETECTION_MODEL_CONFIGS[modelId] || {
    label: modelId || "Özel model",
    note: "Özel model kimliği kullanılacak. RT-DETR, Ultralytics/YOLO veya desteklenen segmentasyon biçimlerinden biri olmalı.",
    output: "özel",
    thresholdLabel: "Eşik",
    defaultThreshold: 0.55,
    defaultLabels: "text_bubble,text_free",
    labelOptions: DETECT_LABEL_OPTIONS,
    showLabelMode: true,
    showMergeGap: false,
  };
}

function roundDetectorPercent(value) {
  return Number(((Number(value) || 0) * 100).toFixed(3));
}

function ModelNameInput({ value, options, onChange }) {
  return (
    <>
      <input
        list="gemini-model-options"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="gemini-3-flash-preview"
        autoComplete="off"
      />
      <datalist id="gemini-model-options">
        {options.map(([optionValue, label]) => (
          <option key={optionValue} value={optionValue}>{label}</option>
        ))}
      </datalist>
    </>
  );
}

function extractBrushMask(canvas) {
  if (!canvas) throw new Error("Fırça maskesi bulunamadı.");
  const context = canvas.getContext("2d");
  const imageData = context.getImageData(0, 0, canvas.width, canvas.height);
  const pixels = imageData.data;
  let left = canvas.width;
  let top = canvas.height;
  let right = 0;
  let bottom = 0;
  let found = false;
  for (let index = 3; index < pixels.length; index += 4) {
    if (pixels[index] === 0) continue;
    const pixel = (index - 3) / 4;
    const x = pixel % canvas.width;
    const y = Math.floor(pixel / canvas.width);
    left = Math.min(left, x);
    top = Math.min(top, y);
    right = Math.max(right, x + 1);
    bottom = Math.max(bottom, y + 1);
    found = true;
  }
  if (!found) throw new Error("Fırça maskesi boş.");
  left = Math.max(0, left - 2);
  top = Math.max(0, top - 2);
  right = Math.min(canvas.width, right + 2);
  bottom = Math.min(canvas.height, bottom + 2);
  const width = right - left;
  const height = bottom - top;
  const cropped = document.createElement("canvas");
  cropped.width = width;
  cropped.height = height;
  cropped.getContext("2d").drawImage(canvas, left, top, width, height, 0, 0, width, height);
  return {
    mask: cropped.toDataURL("image/png"),
    bbox: { x: left, y: top, w: width, h: height },
  };
}

function visibleJob(jobs) {
  return jobs.find((job) => ["queued", "running", "failed"].includes(job.status)) || recentCompletedJob(jobs);
}

function recentCompletedJob(jobs) {
  const job = jobs.find((item) => item.status === "done");
  if (!job?.completedAt) return null;
  return Date.now() - new Date(job.completedAt).getTime() < 120000 ? job : null;
}

function jobLabel(type) {
  return {
    detect: "Algılama",
    ocr: "OCR",
    inpaint: "Temizleme",
    "manual-inpaint": "Fırça",
    "restore-brush": "Orijinal",
    translate: "Çeviri",
    place: "Yerleştirme",
    unplace: "Kaldırma",
    save: "Kaydetme",
  }[type] || type;
}

function detectorJobText(detector) {
  if (!detector?.title) return "";
  const activeTitle = detector.activeTitle || detector.title;
  if (detector.source === "fallback" && activeTitle !== detector.title) {
    return `Çalışan model: ${activeTitle} | Seçili model: ${detector.title}`;
  }
  if (detector.source === "none") {
    return `Çalışan model: ${activeTitle} | Sonuç bulunmadı`;
  }
  return `Çalışan model: ${activeTitle}`;
}

function isEditableTarget(target) {
  if (!target) return false;
  const tagName = target.tagName?.toLowerCase();
  return target.isContentEditable || ["input", "textarea", "select"].includes(tagName);
}

function positiveNumber(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function resizedBox(origin, handle, dx, dy, pageWidth, pageHeight) {
  const minSize = 18;
  let left = Number(origin.x || 0);
  let top = Number(origin.y || 0);
  let right = left + Number(origin.w || minSize);
  let bottom = top + Number(origin.h || minSize);

  if (handle.includes("w")) {
    left = clamp(left + dx, 0, right - minSize);
  }
  if (handle.includes("e")) {
    right = clamp(right + dx, left + minSize, pageWidth);
  }
  if (handle.includes("n")) {
    top = clamp(top + dy, 0, bottom - minSize);
  }
  if (handle.includes("s")) {
    bottom = clamp(bottom + dy, top + minSize, pageHeight);
  }

  return {
    ...origin,
    x: roundLayout(left),
    y: roundLayout(top),
    w: roundLayout(right - left),
    h: roundLayout(bottom - top),
  };
}

function roundLayout(value) {
  return Math.round(value * 10) / 10;
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

function diffTextStyle(nextStyle, currentStyle) {
  return Object.fromEntries(
    Object.entries(nextStyle || {}).filter(([key, value]) => !Object.is(value, currentStyle?.[key])),
  );
}

function boxLabel(box, pages) {
  const pageIndex = Math.max(0, pages.findIndex((page) => page.id === box.pageId));
  return `${pageIndex + 1}.${box.order}`;
}

function boxClassName(box, activeBoxId, selectedBoxIds) {
  return [
    "box",
    selectedBoxIds.includes(box.id) ? "selected" : "",
    box.id === activeBoxId ? "active" : "",
  ].filter(Boolean).join(" ");
}

function boxRowClassName(item, activeBox, selectedBoxIds) {
  return [
    "box-row",
    selectedBoxIds.includes(item.id) ? "selected" : "",
    item.id === activeBox?.id ? "active" : "",
  ].filter(Boolean).join(" ");
}

function normalizeStatus(status = "pending") {
  return String(status || "pending").toLowerCase().replace(/[^a-z0-9]+/g, "-");
}

function statusLabel(status) {
  return {
    pending: "Bekliyor",
    detected: "Algılandı",
    ocr: "OCR",
    translated: "Çevrildi",
    cleaned: "Temiz",
    placed: "Yerleşti",
    failed: "Hata",
  }[normalizeStatus(status)] || status || "Bekliyor";
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

function orderManualMasks(items, pages) {
  return items.slice().sort((a, b) => {
    const pageA = pageIndex(pages, a.pageId);
    const pageB = pageIndex(pages, b.pageId);
    if (pageA !== pageB) return pageA - pageB;
    return String(a.createdAt || a.id).localeCompare(String(b.createdAt || b.id));
  });
}

function pageIndex(pages, pageId) {
  const index = pages.findIndex((page) => page.id === pageId);
  return index === -1 ? Number.MAX_SAFE_INTEGER : index;
}

function draftSettings(settings) {
  const ai = settings?.ai || {};
  const editor = settings?.editor || {};
  const reader = settings?.reader || {};
  return {
    editor: {
      defaultFontFamily: editor.defaultFontFamily || "noto-sans-black",
      defaultFontSize: editor.defaultFontSize || 28,
    },
    reader: {
      syncEnabled: reader.syncEnabled || false,
      syncHost: reader.syncHost || "",
      syncPath: reader.syncPath || "~/webtoon-reader/data/library",
    },
    ai: {
      defaultTargetLanguage: ai.defaultTargetLanguage || "TR",
      geminiModel: ai.geminiModel || "gemini-3-flash-preview",
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
      detectorFallbackEnabled: Boolean(ai.detectorFallbackEnabled),
      detectorMinAreaRatio: ai.detectorMinAreaRatio ?? 0.00008,
      detectorMergeGap: ai.detectorMergeGap ?? 18,
      ocrLanguage: ai.ocrLanguage || "en",
      ocrPerspectiveEnabled: ai.ocrPerspectiveEnabled ?? true,
      ocrPerspectiveMinAngle: ai.ocrPerspectiveMinAngle ?? 7,
      ocrPerspectivePadding: ai.ocrPerspectivePadding ?? 1,
      inpaintModel: ai.inpaintModel || "lama",
      aiDevice: ai.aiDevice || "cpu",
      inpaintPadding: ai.inpaintPadding ?? 8,
      inpaintPerspectiveMask: ai.inpaintPerspectiveMask ?? true,
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
    <button type="button" className={active ? "tool active" : "tool"} onClick={onClick} title={label} aria-label={label}>
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
