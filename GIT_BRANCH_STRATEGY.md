# Git Branch Strategy for Opportunity Management

## 🌿 Branch Structure

### **`main` Branch**
- **Purpose:** Production-ready code
- **Deploy to:** Production site on Frappe Cloud
- **Updates:** Only merge from `development` after testing
- **Protection:** Stable, tested code only

### **`development` Branch** ← **New!**
- **Purpose:** Testing and development
- **Deploy to:** Development/staging site (or test locally)
- **Updates:** All new features and fixes go here first
- **Protection:** Can have bugs, experimental features

---

## 🔄 Workflow

### **For New Features or Changes:**

```bash
# 1. Switch to development branch
git checkout development

# 2. Make your changes
# (edit files, add features, etc.)

# 3. Commit changes
git add .
git commit -m "Add new feature"

# 4. Push to development
git push origin development

# 5. Test on Frappe Cloud (development site)
# - Deploy development branch to a test site
# - Or test locally

# 6. If everything works, merge to main
git checkout main
git merge development
git push origin main

# 7. Deploy to production
```

---

## 📦 Deployment Strategy

### **Option 1: Two Sites (Recommended)**

**Setup on Frappe Cloud:**
- **Production Site:** Tracks `main` branch
- **Development Site:** Tracks `development` branch

**Benefits:**
- ✅ Test safely without affecting production
- ✅ Faster deployments (Docker cache reused)
- ✅ Can rollback easily
- ✅ Users not affected by testing

---

## 🚀 Quick Commands

### **Start New Feature:**
```bash
git checkout development
git pull origin development
# Make changes
git add .
git commit -m "Description"
git push origin development
```

### **Merge to Production:**
```bash
# Make sure development is tested
git checkout main
git pull origin main
git merge development
git push origin main
```

---

## 📊 Why Migration Was Pending

**12-13 minutes waiting** happened because:

1. **Job Queue** - Your migration waited in line behind other jobs
2. **Resource Allocation** - Frappe Cloud was allocating resources
3. **Database Lock** - Ensuring no conflicts before starting
4. **Health Checks** - Validating site before migration

**This is normal for shared hosting during peak times.**

---

## 💡 Going Forward

**From now on:**

1. **All changes go to `development` first**
2. **Test there** (locally or on dev site)
3. **Merge to `main`** when stable
4. **Deploy to production** from `main`

**Your development branch is ready!** 🌿
