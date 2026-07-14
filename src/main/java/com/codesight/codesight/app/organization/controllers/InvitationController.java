package com.codesight.codesight.app.organization.controllers;

import com.codesight.codesight.app.organization.dto.InvitationResponseDto;
import com.codesight.codesight.app.organization.services.OrganizationInvitationService;
import com.codesight.codesight.app.user.model.UserModel;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1/invitations")
@RequiredArgsConstructor
public class InvitationController {

    private final OrganizationInvitationService organizationInvitationService;

    @GetMapping("/{token}")
    public ResponseEntity<InvitationResponseDto> getInvitation(@PathVariable String token) {
        return ResponseEntity.ok(organizationInvitationService.getInvitation(token));
    }

    @PostMapping("/{token}/accept")
    public ResponseEntity<InvitationResponseDto> acceptInvitation(
            @PathVariable String token,
            @AuthenticationPrincipal UserModel currentUser
    ) {
        return ResponseEntity.ok(
                organizationInvitationService.acceptInvitation(token, currentUser.getId(), currentUser.getEmail())
        );
    }
}
