package com.codesight.codesight.app.project.services;

import org.springframework.stereotype.Component;

import java.util.concurrent.ConcurrentHashMap;

@Component
public class CloneProgressStore {

    public record CloneProgress(String stage, int percent, String detail) {}

    private final ConcurrentHashMap<String, CloneProgress> map = new ConcurrentHashMap<>();

    public void update(String projectId, String stage, int percent, String detail) {
        map.put(projectId, new CloneProgress(stage, percent, detail));
    }

    public CloneProgress get(String projectId) {
        return map.getOrDefault(projectId, new CloneProgress("idle", 0, ""));
    }

    public void remove(String projectId) {
        map.remove(projectId);
    }
}
