package com.codesight.codesight.app.project.services;

import org.springframework.stereotype.Component;

import java.util.concurrent.ConcurrentHashMap;

@Component
public class AnalysisProgressStore {

    public record AnalysisProgress(String stage, String message) {}

    private final ConcurrentHashMap<String, AnalysisProgress> map = new ConcurrentHashMap<>();

    public void update(String projectId, String stage, String message) {
        map.put(projectId, new AnalysisProgress(stage, message));
    }

    public AnalysisProgress get(String projectId) {
        return map.getOrDefault(projectId, new AnalysisProgress(null, null));
    }

    public void remove(String projectId) {
        map.remove(projectId);
    }
}
