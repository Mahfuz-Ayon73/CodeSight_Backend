package com.codesight.codesight.app.project.services;

import org.eclipse.jgit.lib.ProgressMonitor;

/**
 * Translates JGit's clone task callbacks into the (stage, percent, detail) shape
 * that CloneProgressStore/the frontend polling loop expects. JGit's own task titles
 * ("Receiving objects", "Resolving deltas", "Checking out files") map onto the
 * coarser stage buckets the UI shows as pills.
 */
class GitCloneProgressMonitor implements ProgressMonitor {

    private final CloneProgressStore store;
    private final String projectId;

    private String stage = "connecting";
    private int totalWork = 0;
    private int workDone = 0;

    GitCloneProgressMonitor(CloneProgressStore store, String projectId) {
        this.store = store;
        this.projectId = projectId;
    }

    @Override
    public void start(int totalTasks) {
        // Per-task progress is reported in beginTask/update instead.
    }

    @Override
    public void beginTask(String title, int totalWork) {
        this.totalWork = totalWork;
        this.workDone = 0;
        this.stage = stageFor(title);
        store.update(projectId, stage, 0, title);
    }

    @Override
    public void update(int completed) {
        workDone += completed;
        int percent = totalWork > 0 ? Math.min(100, (int) ((workDone * 100L) / totalWork)) : 0;
        store.update(projectId, stage, percent, null);
    }

    @Override
    public void endTask() {
        store.update(projectId, stage, 100, null);
    }

    @Override
    public boolean isCancelled() {
        return false;
    }

    @Override
    public void showDuration(boolean enabled) {
        // Not needed — we don't render JGit's own duration output.
    }

    private static String stageFor(String title) {
        if (title == null) return "downloading";
        String normalized = title.toLowerCase();
        if (normalized.contains("resolving")) return "resolving";
        if (normalized.contains("checking out") || normalized.contains("updating")) return "finalizing";
        return "downloading";
    }
}
