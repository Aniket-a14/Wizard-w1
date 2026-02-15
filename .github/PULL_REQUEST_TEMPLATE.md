## 🧙‍♂️ Pull Request Template

### Description
Please include a summary of the changes and the related issue. Please also include relevant motivation and context. 

### Type of Change
- [ ] 🐛 Bug fix (non-breaking change which fixes an issue)
- [ ] ✨ New feature (non-breaking change which adds functionality)
- [ ] 💥 Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] 📝 Documentation update

### How Has This Been Tested?
Please describe the tests that you ran to verify your changes. 
- [ ] **The Council verification**: Ensured that the Visualizer, Statistician, and Architect specialist logic is not regressed.
- [ ] **Sandbox compatibility**: Verified execution in the Docker-isolated sandbox with resource limits.
- [ ] **RAG persistence**: Confirmed WorkingMemory integrity if changes involve the storage layer.
- [ ] Automatic CI Tests
- [ ] Manual Smoke Tests

### Checklist
- [ ] My code follows the style guidelines of this project
- [ ] I have performed a self-review of my code
- [ ] I have commented my code, particularly in hard-to-understand areas
- [ ] I have made corresponding changes to the documentation
- [ ] My changes generate no new warnings
- [ ] I have checked that the architecture diagram is still rendering correctly

---
*Note: Every PR requires a human approval from the @Aniket-a14 or other maintainers before merging.*
