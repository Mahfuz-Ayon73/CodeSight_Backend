package com.codesight.codesight.app.organization.controllers;

import com.codesight.codesight.app.organization.dto.CreateInvitationRequestDto;
import com.codesight.codesight.app.organization.dto.InvitationResponseDto;
import com.codesight.codesight.app.organization.dto.OrganizationMemberResponseDto;
import com.codesight.codesight.app.organization.dto.OrganizationRequestDto;
import com.codesight.codesight.app.organization.dto.OrganizationResponseDto;
import com.codesight.codesight.app.organization.services.OrganizationInvitationService;
import com.codesight.codesight.app.organization.services.OrganizationService;
import com.codesight.codesight.app.user.model.UserModel;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/api/v1/organizations")
@RequiredArgsConstructor
public class OrganizationController {

    private final OrganizationService organizationService;
    private final OrganizationInvitationService organizationInvitationService;

    @PostMapping
    public ResponseEntity<OrganizationResponseDto> createOrganization(
            @Valid @RequestBody OrganizationRequestDto request,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        return ResponseEntity.status(HttpStatus.CREATED)
                .body(organizationService.createOrganization(request, currentUser.getId()));
    }

    @GetMapping
    public ResponseEntity<List<OrganizationResponseDto>> listOrganizations(
            @AuthenticationPrincipal UserModel currentUser
    ) {
        return ResponseEntity.ok(organizationService.listMyOrganizations(currentUser.getId()));
    }

    @GetMapping("/{organizationId}")
    public ResponseEntity<OrganizationResponseDto> getOrganization(
            @PathVariable UUID organizationId,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        return ResponseEntity.ok(organizationService.getOrganization(organizationId, currentUser.getId()));
    }

    @GetMapping("/{organizationId}/members")
    public ResponseEntity<List<OrganizationMemberResponseDto>> listMembers(
            @PathVariable UUID organizationId,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        return ResponseEntity.ok(organizationService.listMembers(organizationId, currentUser.getId()));
    }

    @PostMapping("/{organizationId}/invitations")
    public ResponseEntity<InvitationResponseDto> inviteMember(
            @PathVariable UUID organizationId,
            @Valid @RequestBody CreateInvitationRequestDto request,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        return ResponseEntity.status(HttpStatus.CREATED)
                .body(organizationInvitationService.createInvitation(organizationId, currentUser.getId(), request));
    }

    @DeleteMapping("/{organizationId}")
    public ResponseEntity<Void> deleteOrganization(
            @PathVariable UUID organizationId,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        organizationService.deleteOrganization(organizationId, currentUser.getId());
        return ResponseEntity.noContent().build();
    }
}
