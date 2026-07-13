using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;
using System.Text;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

namespace AiCad.SolidWorksHost
{
    [DataContract]
    internal sealed class HostPlan
    {
        [DataMember] public string protocol;
        [DataMember] public string source_sha256;
        [DataMember] public string part_name;
        [DataMember] public string units;
        [DataMember] public double tolerance_mm;
        [DataMember] public string template_path;
        [DataMember] public string output_sldprt;
        [DataMember] public string output_step;
        [DataMember] public List<FeaturePlan> features;
    }

    [DataContract]
    internal sealed class FeaturePlan
    {
        [DataMember] public string id;
        [DataMember] public string type;
        [DataMember] public string purpose;
        [DataMember] public string reasoning;
        [DataMember] public List<string> depends_on;
        [DataMember] public string support_feature;
        [DataMember] public double support_top_z_mm;
        [DataMember] public double resulting_top_z_mm;
        [DataMember] public double depth_mm;
        [DataMember] public string end_condition;
        [DataMember] public ProfilePlan profile;
        [DataMember] public ExpectedState expected;
    }

    [DataContract]
    internal sealed class ProfilePlan
    {
        [DataMember] public string kind;
        [DataMember] public double center_x_mm;
        [DataMember] public double center_y_mm;
        [DataMember] public double? width_mm;
        [DataMember] public double? height_mm;
        [DataMember] public double? radius_mm;
        [DataMember] public int? count;
        [DataMember] public double? bolt_circle_radius_mm;
        [DataMember] public double? start_angle_deg;
        [DataMember] public List<CirclePlan> circles;
    }

    [DataContract]
    internal sealed class CirclePlan
    {
        [DataMember] public double x_mm;
        [DataMember] public double y_mm;
        [DataMember] public double radius_mm;
    }

    [DataContract]
    internal sealed class ExpectedState
    {
        [DataMember] public double volume_before_mm3;
        [DataMember] public double volume_after_mm3;
        [DataMember] public double volume_delta_mm3;
        [DataMember] public double[] bbox_mm;
        [DataMember] public int solid_body_count;
    }

    [DataContract]
    internal sealed class ModelSnapshot
    {
        [DataMember] public int solid_body_count;
        [DataMember] public int body_fault_count;
        [DataMember] public double volume_mm3;
        [DataMember] public double surface_area_mm2;
        [DataMember] public double[] bbox_mm;
    }

    [DataContract]
    internal sealed class FeatureReport
    {
        [DataMember] public string id;
        [DataMember] public string type;
        [DataMember] public string purpose;
        [DataMember] public string support_feature;
        [DataMember] public string support_face_selection_method;
        [DataMember] public double? selected_support_plane_z_mm;
        [DataMember] public string sketch_name;
        [DataMember] public int sketch_autodim_status;
        [DataMember] public int sketch_constraint_status;
        [DataMember] public int profile_segment_count;
        [DataMember] public int explicit_radius_dimension_count;
        [DataMember] public int explicit_center_dimension_count;
        [DataMember] public int explicit_center_relation_count;
        [DataMember] public bool used_fixed_fallback;
        [DataMember] public int feature_error_code;
        [DataMember] public bool feature_warning;
        [DataMember] public string persistent_reference_base64;
        [DataMember] public int persistent_reference_status;
        [DataMember] public bool persistent_reference_resolved;
        [DataMember] public ModelSnapshot before;
        [DataMember] public ModelSnapshot after;
        [DataMember] public double expected_volume_after_mm3;
        [DataMember] public double actual_volume_delta_mm3;
        [DataMember] public bool passed;
        [DataMember] public List<string> checks;
    }

    [DataContract]
    internal sealed class HostReport
    {
        [DataMember] public string protocol;
        [DataMember] public string status;
        [DataMember] public string source_sha256;
        [DataMember] public string solidworks_revision;
        [DataMember] public string output_sldprt;
        [DataMember] public string output_step;
        [DataMember] public int sldprt_save_errors;
        [DataMember] public int sldprt_save_warnings;
        [DataMember] public int step_save_errors;
        [DataMember] public int step_save_warnings;
        [DataMember] public List<FeatureReport> features = new List<FeatureReport>();
        [DataMember] public ModelSnapshot final_state;
        [DataMember] public List<string> errors = new List<string>();
    }

    [DataContract]
    internal sealed class ReopenReport
    {
        [DataMember] public string protocol;
        [DataMember] public string status;
        [DataMember] public string solidworks_revision;
        [DataMember] public string input_sldprt;
        [DataMember] public int open_errors;
        [DataMember] public int open_warnings;
        [DataMember] public int aicad_feature_count;
        [DataMember] public List<string> aicad_feature_names = new List<string>();
        [DataMember] public List<string> feature_errors = new List<string>();
        [DataMember] public ModelSnapshot final_state;
        [DataMember] public List<string> errors = new List<string>();
    }

    internal static class Program
    {
        private const double MillimetersPerMeter = 1000.0;
        private const double CubicMillimetersPerCubicMeter = 1_000_000_000.0;
        private const double SquareMillimetersPerSquareMeter = 1_000_000.0;

        [STAThread]
        private static int Main(string[] args)
        {
            Console.OutputEncoding = new UTF8Encoding(false);
            if (args.Length == 3 && args[0] == "--inspect")
            {
                return InspectSavedPart(Path.GetFullPath(args[1]), Path.GetFullPath(args[2]));
            }
            if (args.Length != 2)
            {
                Console.Error.WriteLine("Usage: AiCad.SolidWorksHost.exe <plan.swplan.json> <report.json> | --inspect <part.SLDPRT> <reopen-report.json>");
                return 2;
            }

            string planPath = Path.GetFullPath(args[0]);
            string reportPath = Path.GetFullPath(args[1]);
            HostReport report = new HostReport { protocol = "AICAD_SOLIDWORKS_REPORT_1", status = "failed" };
            SldWorks app = null;
            ModelDoc2 model = null;
            bool createdApplication = false;
            try
            {
                HostPlan plan = ReadJson<HostPlan>(planPath);
                ValidateEnvelope(plan);
                report.source_sha256 = plan.source_sha256;
                report.output_sldprt = plan.output_sldprt;
                report.output_step = plan.output_step;
                Directory.CreateDirectory(Path.GetDirectoryName(reportPath));
                Directory.CreateDirectory(Path.GetDirectoryName(plan.output_sldprt));
                Directory.CreateDirectory(Path.GetDirectoryName(plan.output_step));
                File.Delete(plan.output_sldprt);
                File.Delete(plan.output_step);

                app = AttachOrStart(out createdApplication);
                report.solidworks_revision = app.RevisionNumber();
                app.CommandInProgress = true;
                model = (ModelDoc2)app.NewDocument(plan.template_path, 0, 0.0, 0.0);
                if (model == null)
                {
                    throw new InvalidOperationException("SolidWorks could not create a part from the configured template.");
                }
                model.ShowFeatureErrorDialog = false;

                var features = new Dictionary<string, Feature>(StringComparer.Ordinal);
                foreach (FeaturePlan featurePlan in plan.features)
                {
                    FeatureReport featureReport = ExecuteFeature(app, model, plan, featurePlan, features);
                    report.features.Add(featureReport);
                    if (!featureReport.passed)
                    {
                        throw new InvalidOperationException("Feature transaction failed: " + featurePlan.id + " :: " + string.Join("; ", featureReport.checks));
                    }
                }

                report.final_state = CaptureSnapshot(model);
                SaveOutputs(app, model, plan, report);
                if (!File.Exists(plan.output_sldprt) || new FileInfo(plan.output_sldprt).Length == 0)
                {
                    throw new InvalidOperationException("SLDPRT output was not created.");
                }
                if (!File.Exists(plan.output_step) || new FileInfo(plan.output_step).Length == 0)
                {
                    throw new InvalidOperationException("STEP output was not created.");
                }
                report.status = "passed";
                WriteJson(reportPath, report);
                Console.WriteLine(reportPath);
                return 0;
            }
            catch (Exception exception)
            {
                report.errors.Add(exception.ToString());
                WriteJson(reportPath, report);
                Console.Error.WriteLine(exception.Message);
                return 1;
            }
            finally
            {
                try
                {
                    if (model != null && app != null)
                    {
                        app.CloseDoc(model.GetTitle());
                    }
                    if (app != null)
                    {
                        app.CommandInProgress = false;
                        if (createdApplication)
                        {
                            app.ExitApp();
                        }
                    }
                }
                catch
                {
                    // Cleanup must not hide the original result.
                }
                ReleaseCom(model);
                ReleaseCom(app);
            }
        }

        private static int InspectSavedPart(string partPath, string reportPath)
        {
            var report = new ReopenReport
            {
                protocol = "AICAD_SOLIDWORKS_REOPEN_REPORT_1",
                status = "failed",
                input_sldprt = partPath,
            };
            SldWorks app = null;
            ModelDoc2 model = null;
            bool createdApplication = false;
            try
            {
                if (!File.Exists(partPath)) throw new FileNotFoundException("SLDPRT input does not exist.", partPath);
                Directory.CreateDirectory(Path.GetDirectoryName(reportPath));
                app = AttachOrStart(out createdApplication);
                report.solidworks_revision = app.RevisionNumber();
                app.CommandInProgress = true;
                int openErrors = 0, openWarnings = 0;
                model = (ModelDoc2)app.OpenDoc6(
                    partPath, (int)swDocumentTypes_e.swDocPART, (int)swOpenDocOptions_e.swOpenDocOptions_Silent,
                    "", ref openErrors, ref openWarnings);
                report.open_errors = openErrors;
                report.open_warnings = openWarnings;
                if (model == null || openErrors != 0)
                    throw new InvalidOperationException("SolidWorks could not reopen the saved part; error=" + openErrors);
                model.ShowFeatureErrorDialog = false;
                model.ForceRebuild3(false);
                Feature current = (Feature)model.FirstFeature();
                while (current != null)
                {
                    string name = current.Name;
                    if (!string.IsNullOrEmpty(name) && name.StartsWith("AICAD_", StringComparison.Ordinal))
                    {
                        report.aicad_feature_names.Add(name);
                        int code = current.GetErrorCode2(out bool warning);
                        if (code != 0 || warning)
                            report.feature_errors.Add(name + ":error=" + code + ",warning=" + warning);
                    }
                    current = (Feature)current.GetNextFeature();
                }
                report.aicad_feature_count = report.aicad_feature_names.Count;
                report.final_state = CaptureSnapshot(model);
                if (report.aicad_feature_count == 0) throw new InvalidOperationException("Saved part contains no AICAD features.");
                if (report.feature_errors.Count != 0) throw new InvalidOperationException("Saved part contains feature errors after reopen.");
                if (report.final_state.solid_body_count != 1 || report.final_state.body_fault_count != 0)
                    throw new InvalidOperationException("Saved part body is invalid after reopen.");
                report.status = "passed";
                WriteJson(reportPath, report);
                Console.WriteLine(reportPath);
                return 0;
            }
            catch (Exception exception)
            {
                report.errors.Add(exception.ToString());
                WriteJson(reportPath, report);
                Console.Error.WriteLine(exception.Message);
                return 1;
            }
            finally
            {
                try
                {
                    if (model != null && app != null) app.CloseDoc(model.GetTitle());
                    if (app != null)
                    {
                        app.CommandInProgress = false;
                        if (createdApplication) app.ExitApp();
                    }
                }
                catch { }
                ReleaseCom(model);
                ReleaseCom(app);
            }
        }

        private static void ValidateEnvelope(HostPlan plan)
        {
            if (plan == null || plan.protocol != "AICAD_SOLIDWORKS_1")
            {
                throw new InvalidDataException("Unsupported SolidWorks execution protocol.");
            }
            if (plan.units != "mm" || plan.features == null || plan.features.Count == 0)
            {
                throw new InvalidDataException("SolidWorks plan must use mm and contain features.");
            }
            if (!File.Exists(plan.template_path))
            {
                throw new FileNotFoundException("SolidWorks part template was not found.", plan.template_path);
            }
        }

        private static SldWorks AttachOrStart(out bool created)
        {
            try
            {
                created = false;
                return (SldWorks)Marshal.GetActiveObject("SldWorks.Application");
            }
            catch (COMException)
            {
                Type type = Type.GetTypeFromProgID("SldWorks.Application", true);
                created = true;
                var app = (SldWorks)Activator.CreateInstance(type);
                app.Visible = false;
                app.UserControl = false;
                return app;
            }
        }

        private static FeatureReport ExecuteFeature(SldWorks app, ModelDoc2 model, HostPlan plan, FeaturePlan featurePlan, IDictionary<string, Feature> features)
        {
            var report = new FeatureReport
            {
                id = featurePlan.id,
                type = featurePlan.type,
                purpose = featurePlan.purpose,
                support_feature = featurePlan.support_feature,
                checks = new List<string>(),
                before = CaptureSnapshot(model),
                expected_volume_after_mm3 = featurePlan.expected.volume_after_mm3,
            };
            ValidateExpectedBefore(featurePlan, report.before, plan.tolerance_mm, report.checks);

            Face2 supportFace = null;
            if (featurePlan.type == "base_extrude")
            {
                Feature plane = FirstReferencePlane(model);
                if (plane == null || !plane.Select2(false, 0))
                {
                    throw new InvalidOperationException(featurePlan.id + " could not select the first principal plane.");
                }
            }
            else
            {
                supportFace = SelectPlanarSupportFace(model, featurePlan, features, out double selectedSupportPlaneZMm);
                report.support_face_selection_method = "named_feature_exact_z";
                report.selected_support_plane_z_mm = selectedSupportPlaneZMm;
                byte[] reference = (byte[])model.Extension.GetPersistReference3(supportFace);
                report.persistent_reference_base64 = Convert.ToBase64String(reference);
                object resolved = model.Extension.GetObjectByPersistReference3(reference, out int persistStatus);
                report.persistent_reference_status = persistStatus;
                report.persistent_reference_resolved = resolved != null && persistStatus == 0;
                ReleaseCom(resolved);
                if (!report.persistent_reference_resolved)
                {
                    throw new InvalidOperationException(featurePlan.id + " persistent support-face reference did not resolve.");
                }
            }

            SketchManager sketchManager = model.SketchManager;
            sketchManager.InsertSketch(true);
            Sketch sketch = sketchManager.ActiveSketch;
            if (sketch == null)
            {
                throw new InvalidOperationException(featurePlan.id + " did not enter sketch edit mode.");
            }
            SketchPoint datumPoint = sketchManager.CreatePoint(0.0, 0.0, 0.0);
            if (datumPoint == null)
            {
                throw new InvalidOperationException(featurePlan.id + " could not create its sketch datum point.");
            }
            model.ClearSelection2(true);
            datumPoint.Select4(false, null);
            model.SketchAddConstraints("sgFIXED");
            model.ClearSelection2(true);
            bool originalAddToDb = sketchManager.AddToDB;
            bool originalDisplayWhenAdded = sketchManager.DisplayWhenAdded;
            List<SketchSegment> profileSegments = null;
            try
            {
                // Direct database creation prevents support-face inferencing, snapping,
                // and automatic relations from changing the frozen numeric profile.
                sketchManager.AddToDB = true;
                sketchManager.DisplayWhenAdded = false;
                profileSegments = CreateProfile(app, sketch, sketchManager, featurePlan.profile, featurePlan.support_top_z_mm);
            }
            finally
            {
                sketchManager.DisplayWhenAdded = originalDisplayWhenAdded;
                sketchManager.AddToDB = originalAddToDb;
                model.GraphicsRedraw2();
            }
            report.profile_segment_count = profileSegments == null ? 0 : profileSegments.Count;
            AddExplicitCircleConstraints(
                app, model, sketch, datumPoint, featurePlan.profile, featurePlan.support_top_z_mm, profileSegments,
                out report.explicit_radius_dimension_count,
                out report.explicit_center_dimension_count,
                out report.explicit_center_relation_count);
            report.sketch_autodim_status = sketchManager.FullyDefineSketch(
                true, true,
                (int)swSketchFullyDefineRelationType_e.swSketchFullyDefineRelationType_Horizontal |
                (int)swSketchFullyDefineRelationType_e.swSketchFullyDefineRelationType_Vertical,
                true,
                (int)swAutodimScheme_e.swAutodimSchemeBaseline, datumPoint,
                (int)swAutodimScheme_e.swAutodimSchemeBaseline, datumPoint,
                (int)swAutodimHorizontalPlacement_e.swAutodimHorizontalPlacementAbove,
                (int)swAutodimVerticalPlacement_e.swAutodimVerticalPlacementRight);
            report.sketch_constraint_status = sketch.GetConstrainedStatus();
            if (report.sketch_constraint_status != (int)swConstrainedStatus_e.swFullyConstrained)
            {
                throw new InvalidOperationException(
                    featurePlan.id + " sketch is not fully constrained; status=" + report.sketch_constraint_status + "; " +
                    SketchConstraintDiagnostics(sketch, profileSegments));
            }
            Feature sketchFeature = (Feature)sketch;
            sketchFeature.Name = "AICAD_SKETCH_" + featurePlan.id;
            report.sketch_name = sketchFeature.Name;
            sketchManager.InsertSketch(true);
            model.ClearSelection2(true);
            sketchFeature.Select2(false, 0);

            double depthMeters = featurePlan.depth_mm / MillimetersPerMeter;
            Feature feature;
            if (featurePlan.type == "cut_extrude")
            {
                int endCondition = featurePlan.end_condition == "through_all" ? (int)swEndConditions_e.swEndCondThroughAll : (int)swEndConditions_e.swEndCondBlind;
                feature = model.FeatureManager.FeatureCut4(
                    true, false, false, endCondition, (int)swEndConditions_e.swEndCondBlind,
                    depthMeters, 0.0, false, false, false, false, 0.0, 0.0,
                    false, false, false, false, false, true, true,
                    false, false, false, (int)swStartConditions_e.swStartSketchPlane,
                    0.0, false, true);
            }
            else
            {
                feature = model.FeatureManager.FeatureExtrusion3(
                    true, false, false, (int)swEndConditions_e.swEndCondBlind, (int)swEndConditions_e.swEndCondBlind,
                    depthMeters, 0.0, false, false, false, false, 0.0, 0.0,
                    false, false, false, false, true, true, true,
                    (int)swStartConditions_e.swStartSketchPlane, 0.0, false);
            }
            if (feature == null)
            {
                throw new InvalidOperationException(featurePlan.id + " SolidWorks feature creation returned null.");
            }
            feature.Name = "AICAD_" + featurePlan.id + "_" + featurePlan.type.ToUpperInvariant();
            features.Add(featurePlan.id, feature);
            bool previousDialog = model.ShowFeatureErrorDialog;
            model.ShowFeatureErrorDialog = false;
            model.ForceRebuild3(false);
            model.ShowFeatureErrorDialog = previousDialog;
            report.feature_error_code = feature.GetErrorCode2(out bool warning);
            report.feature_warning = warning;

            if (!string.IsNullOrEmpty(report.persistent_reference_base64))
            {
                byte[] reference = Convert.FromBase64String(report.persistent_reference_base64);
                object resolvedAfter = model.Extension.GetObjectByPersistReference3(reference, out int persistStatusAfter);
                report.persistent_reference_status = persistStatusAfter;
                report.persistent_reference_resolved = resolvedAfter != null && persistStatusAfter == 0;
                ReleaseCom(resolvedAfter);
            }
            report.after = CaptureSnapshot(model);
            report.actual_volume_delta_mm3 = report.after.volume_mm3 - report.before.volume_mm3;
            ValidateAfter(featurePlan, report, plan.tolerance_mm);
            report.passed = report.checks.All(item => item.StartsWith("PASS:", StringComparison.Ordinal));
            return report;
        }

        private static void ValidateExpectedBefore(FeaturePlan plan, ModelSnapshot snapshot, double tolerance, ICollection<string> checks)
        {
            double allowed = VolumeTolerance(plan.expected.volume_before_mm3, tolerance);
            if (Math.Abs(snapshot.volume_mm3 - plan.expected.volume_before_mm3) <= allowed)
                checks.Add("PASS:volume_before");
            else
                checks.Add("FAIL:volume_before expected=" + plan.expected.volume_before_mm3.ToString("R", CultureInfo.InvariantCulture) + " actual=" + snapshot.volume_mm3.ToString("R", CultureInfo.InvariantCulture));
        }

        private static void ValidateAfter(FeaturePlan plan, FeatureReport report, double tolerance)
        {
            if (report.feature_error_code == 0) report.checks.Add("PASS:feature_error_code");
            else report.checks.Add("FAIL:feature_error_code=" + report.feature_error_code);
            if (report.sketch_constraint_status == (int)swConstrainedStatus_e.swFullyConstrained) report.checks.Add("PASS:sketch_fully_constrained");
            else report.checks.Add("FAIL:sketch_constraint_status=" + report.sketch_constraint_status);
            if (report.after.body_fault_count == 0) report.checks.Add("PASS:body_valid");
            else report.checks.Add("FAIL:body_fault_count=" + report.after.body_fault_count);
            if (string.IsNullOrEmpty(plan.support_feature))
                report.checks.Add("PASS:support_plane_not_applicable");
            else if (report.support_face_selection_method == "named_feature_exact_z" &&
                     report.selected_support_plane_z_mm.HasValue &&
                     Math.Abs(report.selected_support_plane_z_mm.Value - plan.support_top_z_mm) <= Math.Max(0.0001, tolerance))
                report.checks.Add("PASS:support_plane_feature_and_z");
            else
                report.checks.Add("FAIL:support_plane_feature_and_z expected_feature=" + plan.support_feature +
                    " expected_z_mm=" + plan.support_top_z_mm.ToString("R", CultureInfo.InvariantCulture));
            if (report.after.solid_body_count == plan.expected.solid_body_count) report.checks.Add("PASS:solid_body_count");
            else report.checks.Add("FAIL:solid_body_count expected=" + plan.expected.solid_body_count + " actual=" + report.after.solid_body_count);
            double allowedVolume = VolumeTolerance(plan.expected.volume_after_mm3, tolerance);
            if (Math.Abs(report.after.volume_mm3 - plan.expected.volume_after_mm3) <= allowedVolume) report.checks.Add("PASS:volume_after");
            else report.checks.Add("FAIL:volume_after expected=" + plan.expected.volume_after_mm3.ToString("R", CultureInfo.InvariantCulture) + " actual=" + report.after.volume_mm3.ToString("R", CultureInfo.InvariantCulture));
            double allowedDelta = VolumeTolerance(Math.Abs(plan.expected.volume_delta_mm3), tolerance);
            if (Math.Abs(report.actual_volume_delta_mm3 - plan.expected.volume_delta_mm3) <= allowedDelta) report.checks.Add("PASS:volume_delta");
            else report.checks.Add("FAIL:volume_delta expected=" + plan.expected.volume_delta_mm3.ToString("R", CultureInfo.InvariantCulture) + " actual=" + report.actual_volume_delta_mm3.ToString("R", CultureInfo.InvariantCulture));
            if (report.after.bbox_mm != null && plan.expected.bbox_mm != null && report.after.bbox_mm.Length == 6 && plan.expected.bbox_mm.Length == 6 && Enumerable.Range(0, 6).All(index => Math.Abs(report.after.bbox_mm[index] - plan.expected.bbox_mm[index]) <= Math.Max(0.01, tolerance * 10)))
                report.checks.Add("PASS:bbox");
            else
                report.checks.Add("FAIL:bbox");
            if (string.IsNullOrEmpty(report.persistent_reference_base64) || report.persistent_reference_resolved)
                report.checks.Add("PASS:persistent_reference");
            else
                report.checks.Add("FAIL:persistent_reference");
        }

        private static double VolumeTolerance(double expected, double linearTolerance)
        {
            return Math.Max(0.5, Math.Max(Math.Abs(expected) * 1e-6, linearTolerance * linearTolerance * linearTolerance * 10.0));
        }

        private static Feature FirstReferencePlane(ModelDoc2 model)
        {
            Feature feature = (Feature)model.FirstFeature();
            while (feature != null)
            {
                if (string.Equals(feature.GetTypeName2(), "RefPlane", StringComparison.Ordinal))
                    return feature;
                feature = (Feature)feature.GetNextFeature();
            }
            return null;
        }

        private static Face2 SelectPlanarSupportFace(
            ModelDoc2 model,
            FeaturePlan feature,
            IDictionary<string, Feature> features,
            out double actualPlaneZMm)
        {
            actualPlaneZMm = double.NaN;
            if (string.IsNullOrEmpty(feature.support_feature) || !features.TryGetValue(feature.support_feature, out Feature supportFeature))
                throw new InvalidOperationException(feature.id + " could not resolve its declared support feature " + feature.support_feature + ".");
            object rawFaces = supportFeature.GetFaces();
            Array faces = rawFaces as Array;
            if (faces == null || faces.Length == 0)
                throw new InvalidOperationException(feature.id + " declared support feature has no current faces: " + feature.support_feature + ".");

            double targetZMeters = feature.support_top_z_mm / MillimetersPerMeter;
            const double planeToleranceMeters = 1e-7;
            Face2 selectedFace = null;
            var horizontalPlaneLevelsMm = new List<string>();
            foreach (object value in faces)
            {
                Face2 candidate = value as Face2;
                if (candidate == null) continue;
                Surface surface = candidate.GetSurface() as Surface;
                double[] box = candidate.GetBox() as double[];
                bool planar = surface != null && surface.IsPlane();
                bool horizontal = planar && box != null && box.Length >= 6 && Math.Abs(box[5] - box[2]) <= planeToleranceMeters;
                if (horizontal)
                    horizontalPlaneLevelsMm.Add((box[2] * MillimetersPerMeter).ToString("R", CultureInfo.InvariantCulture));
                bool exactZ = horizontal && Math.Abs(box[2] - targetZMeters) <= planeToleranceMeters && Math.Abs(box[5] - targetZMeters) <= planeToleranceMeters;
                ReleaseCom(surface);
                if (exactZ)
                {
                    selectedFace = candidate;
                    actualPlaneZMm = (box[2] + box[5]) * MillimetersPerMeter / 2.0;
                    break;
                }
                ReleaseCom(candidate);
            }
            if (selectedFace == null)
                throw new InvalidOperationException(
                    feature.id + " could not resolve an exact-Z planar face on support feature " + feature.support_feature +
                    "; expected_z_mm=" + feature.support_top_z_mm.ToString("R", CultureInfo.InvariantCulture) +
                    "; available_horizontal_z_mm=[" + string.Join(",", horizontalPlaneLevelsMm) + "].");

            model.ClearSelection2(true);
            Entity entity = selectedFace as Entity;
            if (entity == null || !entity.Select4(false, null))
                throw new InvalidOperationException(feature.id + " could not select the exact-Z face of support feature " + feature.support_feature + ".");
            return selectedFace;
        }
        private static List<SketchSegment> CreateProfile(SldWorks app, Sketch sketch, SketchManager manager, ProfilePlan profile, double supportTopZmm)
        {
            var segments = new List<SketchSegment>();
            double[] center = ModelPointToSketch(app, sketch, profile.center_x_mm, profile.center_y_mm, supportTopZmm);
            if (profile.kind == "center_rectangle")
            {
                double halfWidthMm = profile.width_mm.Value / 2.0;
                double halfHeightMm = profile.height_mm.Value / 2.0;
                double[] corner = ModelPointToSketch(
                    app, sketch, profile.center_x_mm + halfWidthMm, profile.center_y_mm + halfHeightMm, supportTopZmm);
                object result = manager.CreateCenterRectangle(center[0], center[1], 0.0, corner[0], corner[1], 0.0);
                if (result == null) throw new InvalidOperationException("SolidWorks failed to create center rectangle.");
                return segments;
            }
            if (profile.circles == null || profile.circles.Count == 0)
                throw new InvalidOperationException("Circle profile contains no primitives.");
            foreach (CirclePlan circle in profile.circles)
            {
                double[] circleCenter = ModelPointToSketch(app, sketch, circle.x_mm, circle.y_mm, supportTopZmm);
                SketchSegment segment = manager.CreateCircleByRadius(circleCenter[0], circleCenter[1], 0.0, circle.radius_mm / MillimetersPerMeter);
                if (segment == null) throw new InvalidOperationException("SolidWorks failed to create circle profile.");
                segments.Add(segment);
            }
            return segments;
        }

        private static string SketchConstraintDiagnostics(Sketch sketch, IList<SketchSegment> segments)
        {
            string segmentStatuses = segments == null
                ? "null"
                : string.Join(",", segments.Select(segment => segment.Status.ToString(CultureInfo.InvariantCulture)));
            var pointStatuses = new List<string>();
            object rawPoints = sketch.GetSketchPoints2();
            Array points = rawPoints as Array;
            if (points != null)
            {
                foreach (object value in points)
                {
                    SketchPoint point = value as SketchPoint;
                    if (point != null)
                    {
                        pointStatuses.Add(point.Status.ToString(CultureInfo.InvariantCulture));
                        ReleaseCom(point);
                    }
                }
            }
            SketchRelationManager relationManager = sketch.RelationManager;
            int relationCount = relationManager == null
                ? -1
                : relationManager.GetRelationsCount((int)swSketchRelationFilterType_e.swAll);
            ReleaseCom(relationManager);
            return "segment_statuses=[" + segmentStatuses + "]; point_statuses=[" +
                string.Join(",", pointStatuses) + "]; relation_count=" + relationCount.ToString(CultureInfo.InvariantCulture);
        }
        private static double[] ModelPointToSketch(SldWorks app, Sketch sketch, double xMm, double yMm, double zMm)
        {
            MathUtility utility = null;
            MathTransform transform = null;
            MathPoint modelPoint = null;
            MathPoint sketchPoint = null;
            try
            {
                utility = (MathUtility)app.GetMathUtility();
                transform = sketch.ModelToSketchTransform;
                modelPoint = (MathPoint)utility.CreatePoint(new double[] {
                    xMm / MillimetersPerMeter, yMm / MillimetersPerMeter, zMm / MillimetersPerMeter
                });
                sketchPoint = (MathPoint)modelPoint.MultiplyTransform(transform);
                double[] coordinates = sketchPoint.ArrayData as double[];
                if (coordinates == null || coordinates.Length < 3)
                    throw new InvalidOperationException("SolidWorks returned an invalid model-to-sketch coordinate transform.");
                return coordinates;
            }
            finally
            {
                ReleaseCom(sketchPoint);
                ReleaseCom(modelPoint);
                ReleaseCom(transform);
                ReleaseCom(utility);
            }
        }

        private static void AddExplicitCircleConstraints(
            SldWorks app,
            ModelDoc2 model,
            Sketch sketch,
            SketchPoint datumPoint,
            ProfilePlan profile,
            double supportTopZmm,
            IList<SketchSegment> segments,
            out int radiusDimensions,
            out int centerDimensions,
            out int centerRelations)
        {
            radiusDimensions = 0;
            centerDimensions = 0;
            centerRelations = 0;
            if (profile.circles == null || profile.circles.Count == 0) return;
            if (segments == null || segments.Count != profile.circles.Count)
                throw new InvalidOperationException("Circle profile segment count does not match its frozen primitives.");
            int preference = (int)swUserPreferenceToggle_e.swInputDimValOnCreate;
            bool originalInputDimensionValue = app.GetUserPreferenceToggle(preference);
            try
            {
                // Headless execution must never open the interactive Modify Dimension dialog.
                app.SetUserPreferenceToggle(preference, false);
                for (int index = 0; index < profile.circles.Count; index++)
                {
                    CirclePlan circle = profile.circles[index];
                    SketchArc arc = segments[index] as SketchArc;
                    SketchPoint centerPoint = arc == null ? null : arc.GetCenterPoint2() as SketchPoint;
                    if (centerPoint == null)
                        throw new InvalidOperationException("SolidWorks could not resolve a circle center point for explicit constraints.");
                    double[] circleCenter = ModelPointToSketch(app, sketch, circle.x_mm, circle.y_mm, supportTopZmm);
                    double zeroTolerance = 1e-10;
                    double dimensionOffset = Math.Max(circle.radius_mm * 1.5 / MillimetersPerMeter, 0.002);

                    if (Math.Abs(circleCenter[0]) <= zeroTolerance && Math.Abs(circleCenter[1]) <= zeroTolerance)
                    {
                        SelectPointPair(model, datumPoint, centerPoint, "coincident circle-center relation");
                        model.SketchAddConstraints("sgCOINCIDENT");
                        centerRelations++;
                    }
                    else
                    {
                        if (Math.Abs(circleCenter[0]) <= zeroTolerance)
                        {
                            SelectPointPair(model, datumPoint, centerPoint, "vertical circle-center relation");
                            model.SketchAddConstraints("sgVERTICALPOINTS2D");
                            centerRelations++;
                        }
                        else
                        {
                            SelectPointPair(model, datumPoint, centerPoint, "horizontal circle-center dimension");
                            object horizontalDimension = model.AddHorizontalDimension2(
                                circleCenter[0] * 0.5,
                                circleCenter[1] - dimensionOffset,
                                0.0);
                            if (horizontalDimension == null)
                                throw new InvalidOperationException("SolidWorks could not create an explicit circle-center X dimension.");
                            ReleaseCom(horizontalDimension);
                            centerDimensions++;
                        }

                        if (Math.Abs(circleCenter[1]) <= zeroTolerance)
                        {
                            SelectPointPair(model, datumPoint, centerPoint, "horizontal circle-center relation");
                            model.SketchAddConstraints("sgHORIZONTALPOINTS2D");
                            centerRelations++;
                        }
                        else
                        {
                            SelectPointPair(model, datumPoint, centerPoint, "vertical circle-center dimension");
                            object verticalDimension = model.AddVerticalDimension2(
                                circleCenter[0] + dimensionOffset,
                                circleCenter[1] * 0.5,
                                0.0);
                            if (verticalDimension == null)
                                throw new InvalidOperationException("SolidWorks could not create an explicit circle-center Y dimension.");
                            ReleaseCom(verticalDimension);
                            centerDimensions++;
                        }
                    }

                    model.ClearSelection2(true);
                    if (!segments[index].Select4(false, null))
                        throw new InvalidOperationException("SolidWorks could not select a circle for its explicit radial dimension.");
                    double[] dimensionText = ModelPointToSketch(
                        app, sketch,
                        circle.x_mm + circle.radius_mm * 1.5,
                        circle.y_mm + circle.radius_mm * 0.5,
                        supportTopZmm);
                    object dimension = model.AddRadialDimension2(dimensionText[0], dimensionText[1], 0.0);
                    if (dimension == null)
                        throw new InvalidOperationException("SolidWorks could not create an explicit circle radius dimension.");
                    ReleaseCom(dimension);
                    model.ClearSelection2(true);
                    radiusDimensions++;
                }
            }
            finally
            {
                app.SetUserPreferenceToggle(preference, originalInputDimensionValue);
            }
        }

        private static void SelectPointPair(ModelDoc2 model, SketchPoint first, SketchPoint second, string purpose)
        {
            model.ClearSelection2(true);
            if (!first.Select4(false, null) || !second.Select4(true, null))
                throw new InvalidOperationException("SolidWorks could not select points for " + purpose + ".");
        }
        private static ModelSnapshot CaptureSnapshot(ModelDoc2 model)
        {
            if (model == null) return new ModelSnapshot { bbox_mm = null };
            var part = (PartDoc)model;
            object rawBodies = part.GetBodies2((int)swBodyType_e.swSolidBody, false);
            object[] bodyObjects = rawBodies as object[];
            if (bodyObjects == null || bodyObjects.Length == 0)
                return new ModelSnapshot { solid_body_count = 0, body_fault_count = 0, volume_mm3 = 0.0, surface_area_mm2 = 0.0, bbox_mm = null };
            var bodies = bodyObjects.Cast<Body2>().ToArray();
            int faults = 0;
            foreach (Body2 body in bodies)
            {
                FaultEntity faultEntity = body.Check3;
                if (faultEntity != null)
                {
                    faults += faultEntity.Count;
                    ReleaseCom(faultEntity);
                }
            }
            MassProperty2 mass = (MassProperty2)model.Extension.CreateMassProperty2();
            if (mass == null) throw new InvalidOperationException("SolidWorks could not create mass properties.");
            mass.UseSystemUnits = true;
            var snapshot = new ModelSnapshot
            {
                solid_body_count = bodies.Length,
                body_fault_count = faults,
                volume_mm3 = mass.Volume * CubicMillimetersPerCubicMeter,
                surface_area_mm2 = mass.SurfaceArea * SquareMillimetersPerSquareMeter,
                bbox_mm = ExtremeBounds(bodies),
            };
            ReleaseCom(mass);
            return snapshot;
        }

        private static double[] ExtremeBounds(IEnumerable<Body2> bodies)
        {
            double minX = double.PositiveInfinity, minY = double.PositiveInfinity, minZ = double.PositiveInfinity;
            double maxX = double.NegativeInfinity, maxY = double.NegativeInfinity, maxZ = double.NegativeInfinity;
            foreach (Body2 body in bodies)
            {
                if (!body.GetExtremePoint(-1, 0, 0, out double x0, out _, out _)) throw new InvalidOperationException("Failed X-min extreme point.");
                if (!body.GetExtremePoint(1, 0, 0, out double x1, out _, out _)) throw new InvalidOperationException("Failed X-max extreme point.");
                if (!body.GetExtremePoint(0, -1, 0, out _, out double y0, out _)) throw new InvalidOperationException("Failed Y-min extreme point.");
                if (!body.GetExtremePoint(0, 1, 0, out _, out double y1, out _)) throw new InvalidOperationException("Failed Y-max extreme point.");
                if (!body.GetExtremePoint(0, 0, -1, out _, out _, out double z0)) throw new InvalidOperationException("Failed Z-min extreme point.");
                if (!body.GetExtremePoint(0, 0, 1, out _, out _, out double z1)) throw new InvalidOperationException("Failed Z-max extreme point.");
                minX = Math.Min(minX, x0); maxX = Math.Max(maxX, x1);
                minY = Math.Min(minY, y0); maxY = Math.Max(maxY, y1);
                minZ = Math.Min(minZ, z0); maxZ = Math.Max(maxZ, z1);
            }
            return new[] { minX, minY, minZ, maxX, maxY, maxZ }.Select(value => value * MillimetersPerMeter).ToArray();
        }

        private static void SaveOutputs(SldWorks app, ModelDoc2 model, HostPlan plan, HostReport report)
        {
            model.ClearSelection2(true);
            int partErrors = 0;
            int partWarnings = 0;
            bool partSaved = model.Extension.SaveAs3(plan.output_sldprt, (int)swSaveAsVersion_e.swSaveAsCurrentVersion, (int)swSaveAsOptions_e.swSaveAsOptions_Silent, null, null, ref partErrors, ref partWarnings);
            report.sldprt_save_errors = partErrors;
            report.sldprt_save_warnings = partWarnings;
            if (!partSaved || partErrors != 0) throw new InvalidOperationException("SLDPRT save failed, errors=" + partErrors + ", warnings=" + partWarnings);
            int activationErrors = 0;
            app.ActivateDoc3(model.GetTitle(), true, (int)swRebuildOnActivation_e.swDontRebuildActiveDoc, ref activationErrors);
            model.ClearSelection2(true);
            int stepErrors = 0;
            int stepWarnings = 0;
            bool stepSaved = model.Extension.SaveAs3(plan.output_step, (int)swSaveAsVersion_e.swSaveAsCurrentVersion, (int)swSaveAsOptions_e.swSaveAsOptions_Silent, null, null, ref stepErrors, ref stepWarnings);
            report.step_save_errors = stepErrors;
            report.step_save_warnings = stepWarnings;
            if (!stepSaved || stepErrors != 0) throw new InvalidOperationException("STEP save failed, errors=" + stepErrors + ", warnings=" + stepWarnings);
        }

        private static T ReadJson<T>(string path)
        {
            using (FileStream stream = File.OpenRead(path))
            {
                return (T)new DataContractJsonSerializer(typeof(T)).ReadObject(stream);
            }
        }

        private static void WriteJson<T>(string path, T value)
        {
            string directory = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);
            string temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            using (FileStream stream = File.Create(temporary))
            {
                var serializer = new DataContractJsonSerializer(typeof(T), new DataContractJsonSerializerSettings { UseSimpleDictionaryFormat = true });
                using (var writer = JsonReaderWriterFactory.CreateJsonWriter(stream, Encoding.UTF8, false, true, "  "))
                {
                    serializer.WriteObject(writer, value);
                }
            }
            if (File.Exists(path)) File.Delete(path);
            File.Move(temporary, path);
        }

        private static void ReleaseCom(object value)
        {
            if (value != null && Marshal.IsComObject(value))
            {
                try { Marshal.FinalReleaseComObject(value); } catch { }
            }
        }
    }
}
